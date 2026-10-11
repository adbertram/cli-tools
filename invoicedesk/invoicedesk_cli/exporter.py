"""Private, checksummed export of current InvoiceDesk data and imported originals."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
from cli_tools_shared.exceptions import ClientError

class Exporter:
    def __init__(self, client, output, resume=False):
        self.client = client
        self.root = Path(output).expanduser().absolute()
        if self.root.is_symlink():
            raise ClientError('Export directory cannot be a symbolic link')
        self.root = self.root.resolve()
        self.cached = {}
        if resume:
            try:
                previous = json.loads((self.root/'manifest.json').read_text())
            except (OSError, ValueError) as exc:
                raise ClientError(f'Cannot resume export: {exc}') from exc
            if previous.get('schema_version') != 1 or previous.get('service') != 'invoicedesk':
                raise ClientError('Unsupported archive schema')
            self.cached = previous['files']
            for name, metadata in self.cached.items():
                path = self.path(name)
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != metadata['sha256']:
                    raise ClientError(f'Archived file checksum mismatch: {name}')
        else:
            try:
                self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
            except OSError as exc:
                raise ClientError(f'Cannot create export directory: {exc}') from exc
        self.manifest = {'schema_version':1,'service':'invoicedesk','started_at':datetime.now(timezone.utc).isoformat(),'status':'running','files':dict(self.cached),'resources':[],'gaps':[]}
        self.write('manifest.json', self.manifest)

    def path(self, name):
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or not relative.parts:
            raise ClientError(f'Unsafe archived path: {name}')
        path = self.root / name
        if not path.resolve().is_relative_to(self.root.resolve()) or any(p.is_symlink() for p in [path,*path.parents] if p == self.root or self.root in p.parents):
            raise ClientError(f'Unsafe archived path: {name}')
        return path

    def write(self, name, value):
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = value if isinstance(value, bytes) else json.dumps(value,indent=2,ensure_ascii=False).encode()
        temporary = path.with_name(path.name+'.tmp')
        if temporary.is_symlink():
            raise ClientError(f'Unsafe archived path: {name}')
        with temporary.open('wb') as stream:
            os.chmod(temporary,0o600)
            stream.write(data)
        os.replace(temporary,path)
        if name != 'manifest.json':
            self.manifest['files'][name] = {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}

    def run(self):
        snapshot = self.client._make_request('GET','/api/compat/export')
        self.write('invoicedesk.json', snapshot)
        self.manifest['resources'].append({'name':'snapshot','status':'exported'})
        inventory = snapshot.get('archive_files')
        if not isinstance(inventory,list):
            raise ClientError('Export response lacks archive_files inventory')
        jobs = [('originals/'+file['path'],'/api/compat/export-file',{'path':file['path']}) for file in inventory]
        invoices = snapshot.get('invoices')
        if not isinstance(invoices,list):
            raise ClientError('Export response lacks invoices')
        # Snapshot is always refreshed; verified binaries remain reusable on resume.
        for invoice in invoices:
            identifier = str(invoice['id'])
            if '/' in identifier or identifier in {'.','..'}:
                raise ClientError('Unsafe invoice identifier')
            jobs.append((f'invoices/{identifier}.pdf',f'/api/compat/invoices/{identifier}/pdf',None))
        for name,endpoint,params in jobs:
            try:
                if name.startswith('invoices/') or name not in self.cached:
                    response = self.client._make_request('GET',endpoint,params=params,raw_response=True)
                    if name.startswith('invoices/') and not response.content.startswith(b'%PDF'):
                        raise ClientError('Invalid invoice PDF')
                    self.write(name,response.content)
                self.manifest['resources'].append({'name':name,'status':'exported'})
            except (ClientError,OSError) as exc:
                self.manifest['gaps'].append({'resource':name,'reason':str(exc)})
                self.manifest['resources'].append({'name':name,'status':'failed'})
        self.manifest['status'] = 'partial' if self.manifest['gaps'] else 'complete'
        self.manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
        self.write('manifest.json',self.manifest)
        return {'output':str(self.root),'status':self.manifest['status'],'account_count':1,'resource_count':len(self.manifest['resources']),'manifest':str(self.root/'manifest.json')}
