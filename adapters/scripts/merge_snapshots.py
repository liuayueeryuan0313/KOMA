"""Merge one regular timetable source with one laboratory snapshot; report overlaps."""
import argparse
import json
from pathlib import Path
from compile_calendar import atomic_write, normalize


def merge(regular, lab, config):
    if regular.get('sourceAdapter') in ('lab-har','merged') or any(str(r['kcdm']).startswith('lab:') for r in regular['rows']):
        raise ValueError('Provide exactly one regular source; do not merge App and JW together')
    if lab.get('sourceAdapter')!='lab-har' or any(not str(r['kcdm']).startswith('lab:') for r in lab['rows']):
        raise ValueError('Expected laboratory snapshot')
    for key in ('xnxq','beginDate','maxWeekNumber','endDate'):
        if regular[key]!=lab[key]: raise ValueError('Snapshot metadata mismatch: '+key)
    merged={**regular,'sourceAdapter':'merged','rows':regular['rows']+lab['rows'],
            'sources':[regular.get('sourceAdapter','app-h5'),lab['sourceAdapter']]}
    normalized=normalize(merged,config)
    conflicts=[]; rows=normalized['occurrences']
    for i,left in enumerate(rows):
        for right in rows[i+1:]:
            if right['startLocal']>=left['endLocal']: break
            if left['startLocal']<right['endLocal']:
                conflicts.append({'date':left['date'],'left':left,'right':right})
    return merged,{'occurrences':len(rows),'regularOccurrences':len(regular['rows']),
                   'labOccurrences':len(lab['rows']),'overlaps':conflicts,
                   'policy':'Retain both events and report overlap; never silently remove a class'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--regular',required=True); p.add_argument('--lab',required=True)
    p.add_argument('--config',default='config.json'); p.add_argument('--output',default='build/combined.snapshot.json')
    p.add_argument('--report',default='build/merge-report.json'); args=p.parse_args()
    try:
        read=lambda path:json.loads(Path(path).read_text(encoding='utf-8-sig'))
        data,report=merge(read(args.regular),read(args.lab),read(args.config))
        if not data['rows']: raise ValueError('Empty merged calendar')
        atomic_write(args.report,json.dumps(report,ensure_ascii=False,indent=2))
        atomic_write(args.output,json.dumps(data,ensure_ascii=False,indent=2))
        print(json.dumps({'state':'READY','occurrences':report['occurrences'],'overlaps':len(report['overlaps'])}))
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps({'state':'DATA_INVALID','message':str(error)},ensure_ascii=False)); raise SystemExit(4)


if __name__=='__main__': main()
