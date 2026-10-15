"""校园发现网页验收服务器：使用临时数据库及独立媒体目录。"""
import argparse
import json
import tempfile
from pathlib import Path
import uvicorn
from PIL import Image,ImageDraw
from campus.app import create_app
from campus.auth import AuthService
from campus.db import Database

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8001)
    args=parser.parse_args()
    runtime=Path(__file__).resolve().parents[1]/'.runtime'
    runtime.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='campus-discovery-demo-') as temp:
        db=Database(Path(temp)/'demo.sqlite3');db.initialize()
        auth=AuthService(db);auth.provision_demo_accounts()
        images=[]
        for index,color in enumerate(['#d6e9df','#dde8f7']):
            path=Path(temp)/f'fixture-{index}.png'
            image=Image.new('RGB',(800,480),color);draw=ImageDraw.Draw(image)
            draw.rectangle((100,170,700,400),fill='#486c68');draw.rectangle((360,100,440,400),fill='#d4bb81')
            draw.ellipse((350,55,450,155),fill='#f4d16a' if index else '#3b4e59')
            image.save(path);images.append(str(path))
        manifest=dict(database=str(db.path),accounts_path=str(auth.accounts_path),media_dir=str(Path(temp)/'discovery-media'),fixture_images=images,base_url=f'http://localhost:{args.port}')
        (runtime/'discovery-demo.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        print('测试信息：'+str(runtime/'discovery-demo.json'),flush=True)
        uvicorn.run(create_app(db.path),host='127.0.0.1',port=args.port)

if __name__=='__main__':main()
