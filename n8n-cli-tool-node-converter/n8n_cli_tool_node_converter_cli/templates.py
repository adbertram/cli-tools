"""TypeScript template strings for n8n node package generation."""

PACKAGE_JSON = """{
  "name": "n8n-nodes-%(name)s",
  "version": "%(version)s",
  "description": "n8n node for %(display_name)s CLI",
  "keywords": [
    "n8n-community-node-package",
    "%(name)s"
  ],
  "license": "MIT",
  "homepage": "",
  "author": {
    "name": "Adam"
  },
  "repository": {
    "type": "git",
    "url": ""
  },
  "main": "index.js",
  "scripts": {
    "build": "tsc && gulp build:icons",
    "dev": "tsc --watch",
    "format": "prettier nodes credentials --write",
    "lint": "tslint -p tsconfig.json -c tslint.json",
    "lintfix": "tslint --fix -p tsconfig.json -c tslint.json"
  },
  "files": [
    "dist"
  ],
  "n8n": {
    "n8nNodesApiVersion": 1,
    "credentials": [
      "dist/credentials/%(pascal_name)sApi.credentials.js"
    ],
    "nodes": [
      "dist/nodes/%(pascal_name)s/%(pascal_name)s.node.js"
    ]
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "n8n-workflow": "*",
    "typescript": "~5.3.0"
  },
  "peerDependencies": {
    "n8n-workflow": "*"
  }
}
"""

TSCONFIG = """{
  "compilerOptions": {
    "strict": true,
    "module": "commonjs",
    "target": "es2019",
    "lib": ["es2019"],
    "declaration": true,
    "skipLibCheck": true,
    "sourceMap": true,
    "outDir": "./dist",
    "rootDir": ".",
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true
  },
  "include": [
    "nodes/**/*.ts",
    "credentials/**/*.ts"
  ],
  "exclude": [
    "node_modules",
    "dist"
  ]
}
"""

CREDENTIAL_TEMPLATE = """import {
\tICredentialType,
\tINodeProperties,
} from 'n8n-workflow';

export class %(pascal_name)sApi implements ICredentialType {
\tname = '%(camel_name)sApi';
\tdisplayName = '%(display_name)s API';
\tproperties: INodeProperties[] = [
%(credential_fields)s
\t];
}
"""

CREDENTIAL_FIELD_TEMPLATE = """\t\t{
\t\t\tdisplayName: '%(display_name)s',
\t\t\tname: '%(field_name)s',
\t\t\ttype: '%(field_type)s',%(type_options)s
\t\t\tdefault: '%(default)s',%(required)s
\t\t},"""

NODE_TEMPLATE = """import {
\tIExecuteFunctions,
\tINodeExecutionData,
\tINodeType,
\tINodeTypeDescription,
\tNodeOperationError,
} from 'n8n-workflow';

import { execSync } from 'child_process';

export class %(pascal_name)s implements INodeType {
\tdescription: INodeTypeDescription = {
\t\tdisplayName: '%(display_name)s',
\t\tname: '%(camel_name)s',
\t\ticon: 'file:%(name)s.svg',
\t\tgroup: ['transform'],
\t\tversion: 1,
\t\tsubtitle: '={{$parameter["operation"] + ": " + $parameter["resource"]}}',
\t\tdescription: '%(description)s',
\t\tdefaults: {
\t\t\tname: '%(display_name)s',
\t\t},
\t\tinputs: ['main'],
\t\toutputs: ['main'],
\t\tcredentials: [
\t\t\t{
\t\t\t\tname: '%(camel_name)sApi',
\t\t\t\trequired: true,
\t\t\t},
\t\t],
\t\tproperties: [
%(resource_property)s
%(operation_properties)s
%(field_properties)s
\t\t],
\t};

\tasync execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
\t\tconst resource = this.getNodeParameter('resource', 0) as string;
\t\tconst operation = this.getNodeParameter('operation', 0) as string;
\t\tconst items = this.getInputData();
\t\tconst returnData: INodeExecutionData[] = [];

\t\tfor (let i = 0; i < items.length; i++) {
\t\t\ttry {
\t\t\t\tconst args: string[] = [resource, operation];

%(execute_body)s

\t\t\t\tconst cmd = `%(cli_command)s ${args.join(' ')}`;

\t\t\t\tlet stdout: string;
\t\t\t\ttry {
\t\t\t\t\tstdout = execSync(cmd, {
\t\t\t\t\t\tencoding: 'utf-8',
\t\t\t\t\t\ttimeout: 60000,
\t\t\t\t\t\tstdio: ['pipe', 'pipe', 'pipe'],
\t\t\t\t\t});
\t\t\t\t} catch (execError: any) {
\t\t\t\t\tconst errorMessage = execError.stderr || execError.message || 'CLI command failed';
\t\t\t\t\tthrow new NodeOperationError(this.getNode(), `CLI error: ${errorMessage}`, { itemIndex: i });
\t\t\t\t}

\t\t\t\tconst trimmed = stdout.trim();
\t\t\t\tif (!trimmed) {
\t\t\t\t\treturnData.push({ json: { success: true }, pairedItem: { item: i } });
\t\t\t\t\tcontinue;
\t\t\t\t}

\t\t\t\tlet result: any;
\t\t\t\ttry {
\t\t\t\t\tresult = JSON.parse(trimmed);
\t\t\t\t} catch {
\t\t\t\t\treturnData.push({ json: { output: trimmed }, pairedItem: { item: i } });
\t\t\t\t\tcontinue;
\t\t\t\t}

\t\t\t\tif (Array.isArray(result)) {
\t\t\t\t\tfor (const item of result) {
\t\t\t\t\t\treturnData.push({ json: item, pairedItem: { item: i } });
\t\t\t\t\t}
\t\t\t\t} else {
\t\t\t\t\treturnData.push({ json: result, pairedItem: { item: i } });
\t\t\t\t}
\t\t\t} catch (error) {
\t\t\t\tif (this.continueOnFail()) {
\t\t\t\t\treturnData.push({
\t\t\t\t\t\tjson: { error: (error as Error).message },
\t\t\t\t\t\tpairedItem: { item: i },
\t\t\t\t\t});
\t\t\t\t\tcontinue;
\t\t\t\t}
\t\t\t\tthrow error;
\t\t\t}
\t\t}

\t\treturn [returnData];
\t}
}
"""

NODE_JSON_TEMPLATE = """{
  "node": "n8n-nodes-%(name)s.%(camel_name)s",
  "nodeVersion": "1.0",
  "codexVersion": "1.0",
  "categories": ["Miscellaneous"],
  "resources": {
    "primaryDocumentation": [
      {
        "url": ""
      }
    ]
  }
}
"""

README_TEMPLATE = """# n8n-nodes-%(name)s

This is an n8n community node for **%(display_name)s**. It wraps the `%(cli_command)s` CLI tool to provide %(display_name)s functionality within n8n workflows.

## Installation

Install this node in your n8n instance:

```bash
cd ~/.n8n/custom
npm install /path/to/n8n-nodes-%(name)s
```

Then restart n8n.

## Resources

%(resources_list)s

## Operations

%(operations_list)s

## Credentials

This node requires %(display_name)s API credentials. The CLI tool (`%(cli_command)s`) handles authentication via its own `.env` file - ensure the CLI is properly configured on the machine running n8n.

## Development

```bash
npm install
npm run build
```
"""
