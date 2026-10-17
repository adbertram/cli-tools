"""Private, checksummed export of current InvoiceDesk data and imported originals."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
from cli_tools_shared.exceptions import ClientError

def valid_file_metadata(value):
    if not isinstance(value, dict) or type(value.get('bytes')) is not int or value['bytes'] < 0:
        return False
    checksum = value.get('sha256')
    return isinstance(checksum, str) and len(checksum) == 64 and all(c in '0123456789abcdef' for c in checksum)


class Exporter:
    def __init__(self, client, output, resume=False):
        self.client = client
        self.root = Path(output).expanduser().absolute()
        if self.root.is_symlink():
            raise ClientError('Export directory cannot be a symbolic link')
        self.root = self.root.resolve()
        self.cached = {}
        self.snapshot = client._make_request('GET', '/api/compat/export')
        if not isinstance(self.snapshot, dict):
            raise ClientError('Invalid export response: expected object')
        identity = self.snapshot.get('source_identity')
        if not isinstance(identity, str) or not identity.strip():
            raise ClientError('Export response lacks source_identity')
        inventory = self.snapshot.get('archive_files')
        invoices = self.snapshot.get('invoices')
        if not isinstance(inventory, list) or not isinstance(invoices, list):
            raise ClientError('Invalid export response: archive_files and invoices must be lists')
        for original in inventory:
            if not valid_file_metadata(original) or not isinstance(original.get('path'), str):
                raise ClientError('Invalid export response: original requires path, bytes and SHA-256')
            self.path('originals/' + original['path'])
        for invoice in invoices:
            if not isinstance(invoice, dict) or not isinstance(invoice.get('id'), (str, int)) or isinstance(invoice['id'], bool):
                raise ClientError('Invalid export response: invoice requires identifier')
            identifier = str(invoice['id'])
            if '/' in identifier or identifier in {'.', '..'}:
                raise ClientError('Unsafe invoice identifier')
            self.path(f"invoices/{identifier}.pdf")
        if resume:
            try:
                previous = json.loads((self.root/'manifest.json').read_text())
            except (OSError, ValueError) as exc:
                raise ClientError(f'Cannot resume export: {exc}') from exc
            if not isinstance(previous, dict):
                raise ClientError('Invalid archive manifest: expected object')
            if previous.get('schema_version') != 1 or previous.get('service') != 'invoicedesk':
                raise ClientError('Unsupported archive schema')
            if previous.get('source_identity') != identity:
                raise ClientError('Cannot resume export: source identity missing or different')
            self.cached = previous.get('files')
            if not isinstance(self.cached, dict):
                raise ClientError('Invalid archive manifest: files must be an object')
            for name, metadata in self.cached.items():
                if not isinstance(name, str) or not valid_file_metadata(metadata):
                    raise ClientError('Invalid archive manifest: file metadata requires path, bytes and SHA-256')
                path = self.path(name)
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != metadata['sha256']:
                    raise ClientError(f'Archived file checksum mismatch: {name}')
        else:
            try:
                self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
            except OSError as exc:
                raise ClientError(f'Cannot create export directory: {exc}') from exc
        self.manifest = {'schema_version':1,'service':'invoicedesk','source_identity':identity,'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','files':dict(self.cached),'resources':[],'gaps':[]}
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
        snapshot = self.snapshot
        self.write('invoicedesk.json', snapshot)
        self.manifest['resources'].append({'name':'snapshot','status':'exported'})
        inventory = snapshot['archive_files']
        jobs = [('originals/'+file['path'],'/api/compat/export-file',{'path':file['path']},file) for file in inventory]
        invoices = snapshot['invoices']
        # Snapshot is always refreshed; verified binaries remain reusable on resume.
        for invoice in invoices:
            identifier = str(invoice['id'])
            jobs.append((f'invoices/{identifier}.pdf',f'/api/compat/invoices/{identifier}/pdf',None,None))
        for name,endpoint,params,original in jobs:
            try:
                cached = self.cached.get(name)
                reusable = original is not None and cached is not None and original.get('sha256') == cached['sha256'] and original.get('bytes') == cached['bytes']
                if not reusable:
                    response = self.client._make_request('GET',endpoint,params=params,raw_response=True)
                    if name.startswith('invoices/') and not response.content.startswith(b'%PDF'):
                        raise ClientError('Invalid invoice PDF')
                    if original is not None:
                        if len(response.content) != original.get('bytes') or hashlib.sha256(response.content).hexdigest() != original.get('sha256'):
                            raise ClientError('Original does not match source inventory')
                    self.write(name,response.content)
                self.manifest['resources'].append({'name':name,'status':'exported'})
            except (ClientError,OSError) as exc:
                self.manifest['gaps'].append({'resource':name,'reason':str(exc)})
                self.manifest['resources'].append({'name':name,'status':'failed'})
        self.manifest['status'] = 'partial' if self.manifest['gaps'] else 'complete'
        self.manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
        self.write('manifest.json',self.manifest)
        return {'output':str(self.root),'status':self.manifest['status'],'account_count':1,'resource_count':len(self.manifest['resources']),'manifest':str(self.root/'manifest.json')}
