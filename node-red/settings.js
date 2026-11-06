module.exports = { uiPort: 1880, uiHost: '127.0.0.1', flowFile: 'flows.json',
  credentialSecret: process.env.NODE_RED_CREDENTIAL_SECRET || undefined,
  editorTheme: { projects: { enabled: false } } };
