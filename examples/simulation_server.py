"""Start the persistent, isolated demo (default http://127.0.0.1:8001)."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import threading
import webbrowser

import uvicorn
from campus.app import create_app
from .simulation_dataset import aware_time, current_directory, generate


def demo_app(directory, *, frozen=False):
    directory=Path(directory).resolve()
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format_version')!=1:raise ValueError('不支持的演示库版本')
    if not (directory/'demo.sqlite3').is_file():raise FileNotFoundError('演示数据库不存在')
    observation=aware_time(manifest['observation'])
    anchor=aware_time(manifest['created_at'])
    def clock():
        return observation if frozen else observation+(datetime.now(timezone.utc)-anchor)
    app=create_app(directory/'demo.sqlite3',business_clock=clock)

    @app.get('/api/simulation',tags=['模拟环境'])
    def simulation_context():
        return dict(simulated=True,observation=observation.isoformat(),server_time=clock().isoformat(),
                    clock_mode='frozen' if frozen else 'elapsed_since_generation',seed=manifest['seed'])
    return app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,help='指定已有演示目录')
    parser.add_argument('--new',action='store_true',help='生成新目录并设为当前演示；旧目录保留')
    parser.add_argument('--at',help='新建时的带时区观察时间')
    parser.add_argument('--seed',type=int,default=20261017)
    parser.add_argument('--port',type=int,default=8001)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--freeze-clock',action='store_true',help='始终停在原观察时点，用于静态讲解')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if args.directory and (args.new or args.at):parser.error('--directory不能与--new或--at合用')
    if args.at and not args.new:parser.error('--at需与--new合用')
    if not 1<=args.port<=65535:parser.error('端口须在1—65535')
    with socket.socket() as listener:
        try:listener.bind((args.host,args.port))
        except OSError as exc:raise SystemExit(f'端口{args.port}不可用，请停止原演示进程或使用--port换一个端口') from exc
    if args.directory:directory=args.directory.resolve()
    elif args.new:directory=generate(at=args.at,seed=args.seed)
    else:
        try:directory=current_directory()
        except ValueError:directory=generate(seed=args.seed)
    app=demo_app(directory,frozen=args.freeze_clock)
    url=f'http://127.0.0.1:{args.port}/'
    print(f'独立模拟环境：{url}',flush=True)
    print(f'数据库：{directory / "demo.sqlite3"}',flush=True)
    print(f'账号清单：{directory / "accounts.json"}',flush=True)
    print(f'生成时验收：{directory / "acceptance.md"}',flush=True)
    print('重复启动复用该目录；按Ctrl+C停止。使用--new生成新的演示，旧记录保留。',flush=True)
    if not args.no_browser:
        timer=threading.Timer(1.5,lambda:webbrowser.open(url));timer.daemon=True;timer.start()
    uvicorn.run(app,host=args.host,port=args.port)


if __name__=='__main__':main()
