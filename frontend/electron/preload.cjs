const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electron', {
  notifyReady: () => ipcRenderer.send('renderer-ready'),
  onBackendReady: (callback) =>
    ipcRenderer.on('backend-ready', (_, ready) => callback(ready)),
  onBackendLog: (callback) =>
    ipcRenderer.on('backend-log', (_, log) => callback(log)),
})
