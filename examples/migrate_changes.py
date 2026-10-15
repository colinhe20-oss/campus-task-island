"""备份并验证 schema 12 迁移；仅核对旧列，不重写业务内容。请先停止目标服务。"""
import argparse,hashlib,json,shutil,sqlite3
from datetime import datetime
from pathlib import Path
from campus.db import Database

def media_hash(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()} if root.exists() else {}

def old_data(c,columns=None):
    if columns is None:
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        columns={table:[r[1] for r in c.execute(f'PRAGMA table_info("{table}")')] for table in tables}
    result={}
    for table,names in columns.items():
        fields=','.join('"'+name+'"' for name in names)
        rows=[tuple(r) for r in c.execute(f'SELECT {fields} FROM "{table}"')]
        encoded=sorted(json.dumps(row,ensure_ascii=False,default=str) for row in rows)
        result[table]=dict(columns=names,count=len(rows),sha256=hashlib.sha256('\n'.join(encoded).encode()).hexdigest())
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--db',default='.runtime/campus.sqlite3');parser.add_argument('--report',default='.runtime/changes-migration-report.json');args=parser.parse_args()
    path=Path(args.db).resolve()
    if not path.is_file():raise SystemExit('目标数据库不存在，停止迁移')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S');backup=path.with_name(path.stem+'.before-changes-'+stamp+'.sqlite3')
    media=path.parent/'discovery-media';media_backup=path.parent/('discovery-media.before-changes-'+stamp)
    with sqlite3.connect(path) as c:
        c.execute('BEGIN');old_schema=c.execute('PRAGMA user_version').fetchone()[0]
        before=old_data(c)
        with sqlite3.connect(backup) as b:c.backup(b)
    files=media_hash(media)
    if media.exists():shutil.copytree(media,media_backup)
    Database(path).initialize()
    with sqlite3.connect(path) as c:
        after=old_data(c,{t:r['columns'] for t,r in before.items()})
        checks=dict(old_columns_unchanged=before==after,integrity=c.execute('PRAGMA integrity_check').fetchone()[0]=='ok',foreign_keys=not c.execute('PRAGMA foreign_key_check').fetchall(),media_unchanged=files==media_hash(media),legacy_ids_preserved=c.execute('SELECT COUNT(*) FROM task_extensions e LEFT JOIN task_changes r ON r.id=e.id WHERE r.id IS NULL').fetchone()[0]==0,current_snapshots=c.execute('SELECT COUNT(*) FROM tasks t LEFT JOIN task_agreements a ON a.task_id=t.id AND a.version=t.terms_version WHERE a.task_id IS NULL').fetchone()[0]==0)
        schema=c.execute('PRAGMA user_version').fetchone()[0];tables=c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
    report=dict(database=str(path),backup=str(backup),media_backup=str(media_backup) if media.exists() else None,old_schema=old_schema,schema=schema,table_count=tables,before=before,after=after,media_files=files,checks=checks,passed=all(checks.values()))
    Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(backup=str(backup),checks=checks,schema=schema,tables=tables),ensure_ascii=False))
    if not report['passed']:raise SystemExit('迁移核对失败，请保留备份并检查报告')

if __name__=='__main__':main()
