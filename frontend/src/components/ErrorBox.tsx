export function ErrorBox({message, retry}: {message: string; retry?: () => void}) {
  return <div className="notice error" role="alert"><strong>Something needs attention</strong><p>{message}</p>{retry && <button onClick={retry} className="secondary">Retry connection</button>}</div>
}
