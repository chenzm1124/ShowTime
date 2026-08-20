import asyncio, json
from sqlalchemy import select, desc
from app.db.session import AsyncSessionLocal
from app.models.task import Task

async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Task).order_by(desc(Task.id)).limit(8))).scalars().all()
        for t in rows:
            try:
                ep = json.loads(t.extra_params) if t.extra_params else None
            except Exception:
                ep = None
            sp = ep.get('selected_photos', []) if isinstance(ep, dict) else []
            failed = [p for p in sp if '_retouch_failed=' in (p.get('processed_url') or '')]
            print(f'task_id={t.id} status={t.status} total_count={t.total_count} processed={t.processed_count} selected_photos={len(sp)} failed={len(failed)}')
            for p in sp[:10]:
                flag = 'FAIL' if '_retouch_failed=' in (p.get('processed_url') or '') else 'OK  '
                pid = p.get('photo_id')
                purl = (p.get('processed_url') or '')[:90]
                print('   ', flag, 'photo=' + str(pid), 'processed=' + purl)
asyncio.run(main())
