interface ConnectionStatusProps {
  isConnected: boolean
}

function ConnectionStatus({ isConnected }: ConnectionStatusProps) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={`w-2 h-2 rounded-full ${
          isConnected ? 'bg-green-500' : 'bg-red-500'
        }`}
      />
      <span className={`text-sm ${isConnected ? 'text-green-600' : 'text-red-500'}`}>
        {isConnected ? '연결됨' : '연결 끊김'}
      </span>
    </div>
  )
}

export default ConnectionStatus
