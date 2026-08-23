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
    "name": "CLI Tools contributors"
  },
  "main": "index.js",
  "scripts": {
    "build": "tsc && find nodes -name '*.svg' -exec cp {} dist/nodes/%(pascal_name)s/ \\\\;",
    "dev": "tsc --watch",
    "format": "prettier nodes credentials --write",
    "lint": "tsc --noEmit",
    "lintfix": "tsc --noEmit"
  },
  "files": [
    "dist",
    "cli"
  ],
  "n8n": {
    "n8nNodesApiVersion": 1,
    "credentials": [
%(credential_paths)s
    ],
    "nodes": [
%(node_paths)s
    ]
  },
  "n8nCliPackage": {
    "packageType": "custom",
    "generator": "n8n-cli",
    "cliTool": "%(cli_command)s"
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

export class %(class_name)s implements ICredentialType {
\tname = '%(type_name)s';
\tdisplayName = '%(display_name)s';
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

import { execFile } from 'child_process';
import * as path from 'path';

export class %(pascal_name)s implements INodeType {
\tdescription: INodeTypeDescription = {
\t\tdisplayName: '%(display_name)s',
\t\tname: '%(camel_name)s',
\t\ticon: 'file:%(name)s.svg',
\t\tgroup: ['transform'],
\t\tversion: 1,
\t\tusableAsTool: true,
\t\tsubtitle: '={{$parameter["operation"] + ": " + $parameter["resource"]}}',
\t\tdescription: '%(description)s',
\t\tdefaults: {
\t\t\tname: '%(display_name)s',
\t\t},
\t\tinputs: ['main'],
\t\toutputs: ['main'],
\t\tcredentials: [
%(credentials_array)s
\t\t],
\t\tproperties: [
%(config_properties)s
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

%(credential_env_setup)s
\t\tfor (let i = 0; i < items.length; i++) {
\t\t\ttry {
%(config_env_code)s
\t\t\t\tconst args: string[] = [resource, operation];

%(execute_body)s

\t\t\t\tconst cliPath = path.resolve(__dirname, '..', '..', '..', 'cli', '.venv', 'bin', '%(cli_command)s');

\t\t\t\tlet stdout: string;
\t\t\t\ttry {
\t\t\t\t\tstdout = await new Promise<string>((resolve, reject) => {
\t\t\t\t\t\tconst child = execFile(cliPath, args, {
\t\t\t\t\t\t\tencoding: 'utf-8',
\t\t\t\t\t\t\ttimeout: 60000,
\t\t\t\t\t\t\tmaxBuffer: 50 * 1024 * 1024%(exec_env_arg)s,
\t\t\t\t\t\t}, (error, stdoutResult, stderrResult) => {
\t\t\t\t\t\t\tif (error) {
\t\t\t\t\t\t\t\tif (stdoutResult && stdoutResult.trim()) {
\t\t\t\t\t\t\t\t\tresolve(stdoutResult);
\t\t\t\t\t\t\t\t} else {
\t\t\t\t\t\t\t\t\treject(new Error(stderrResult || stdoutResult || error.message || 'CLI command failed'));
\t\t\t\t\t\t\t\t}
\t\t\t\t\t\t\t} else {
\t\t\t\t\t\t\t\tresolve(stdoutResult);
\t\t\t\t\t\t\t}
\t\t\t\t\t\t});
\t\t\t\t\t\tif (child.stdin) {
\t\t\t\t\t\t\tchild.stdin.end();
\t\t\t\t\t\t}
\t\t\t\t\t});
\t\t\t\t} catch (execError: any) {
\t\t\t\t\tthrow new NodeOperationError(this.getNode(), `CLI error: ${execError.message}`, { itemIndex: i });
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
npm install /path/to/%(name)s
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
