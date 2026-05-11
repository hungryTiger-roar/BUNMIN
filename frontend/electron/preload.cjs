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
  getScreenSources: () => ipcRenderer.invoke('get-screen-sources'),
  quitApp: () => ipcRenderer.send('quit-app'),
  // ─── 윈도우 컨트롤 (자체 타이틀바용) ───────────────────────────
  minimizeWindow: () => ipcRenderer.send('window-minimize'),
  toggleMaximizeWindow: () => ipcRenderer.send('window-toggle-maximize'),
  closeWindow: () => ipcRenderer.send('window-close'),
  isWindowMaximized: () => ipcRenderer.invoke('window-is-maximized'),
  onWindowMaximizedChange: (callback) => {
    const handler = (_, maximized) => callback(maximized)
    ipcRenderer.on('window-maximized-change', handler)
    return () => ipcRenderer.off('window-maximized-change', handler)
  },
})
