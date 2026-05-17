const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electron', {
  onBackendReady: (callback) => {
    const handler = (_, ready) => callback(ready)
    ipcRenderer.on('backend-ready', handler)
    return () => ipcRenderer.off('backend-ready', handler)
  },
  onBackendLog: (callback) => {
    const handler = (_, log) => callback(log)
    ipcRenderer.on('backend-log', handler)
    return () => ipcRenderer.off('backend-log', handler)
  },
  onBackendProgress: (callback) => {
    const handler = (_, progress) => callback(progress)
    ipcRenderer.on('backend-progress', handler)
    return () => ipcRenderer.off('backend-progress', handler)
  },
  onBackendModelStatus: (callback) => {
    const handler = (_, models) => callback(models)
    ipcRenderer.on('backend-model-status', handler)
    return () => ipcRenderer.off('backend-model-status', handler)
  },
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
