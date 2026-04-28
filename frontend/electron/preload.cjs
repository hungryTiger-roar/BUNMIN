const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electron', {
  onBackendReady: (callback) =>
    ipcRenderer.on('backend-ready', (_, ready) => callback(ready)),
  onBackendLog: (callback) =>
    ipcRenderer.on('backend-log', (_, log) => callback(log)),
  onBackendProgress: (callback) =>
    ipcRenderer.on('backend-progress', (_, progress) => callback(progress)),
  onBackendModelStatus: (callback) =>
    ipcRenderer.on('backend-model-status', (_, models) => callback(models)),
  getLanIp: () => ipcRenderer.invoke('get-lan-ip'),
  getBackendState: () => ipcRenderer.invoke('get-backend-state'),
})
