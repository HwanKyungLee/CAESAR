"""Run the existing production Stage-1 adapter on every row of one alpha file.

Diagnostic only: no T2 verdict, ranking, or Apply.  This closes the gap between
the four-row Stage-1 sample and a full injection time-series profile.
"""
from __future__ import annotations
import argparse, glob, json, os, sys
from datetime import date
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import fit_explorer as FE
from core.doas_fit import DoasFitter
from tools import optimize_params as OP
from tools.run_zero_base_stage1 import load_selected_scans, select_candidate

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fitset', required=True); p.add_argument('--key', required=True)
    p.add_argument('--alpha', required=True); p.add_argument('--output', required=True)
    p.add_argument('--shift-limit', type=float, nargs=2, required=True)
    p.add_argument('--squeeze-limit', type=float, nargs=2, required=True)
    a = p.parse_args(argv)
    if os.path.exists(a.output): raise SystemExit('ABSTAIN: output exists')
    with open(a.fitset, encoding='utf-8') as fh: scenario = json.load(fh)
    cfg = scenario['channels'][a.key]
    if cfg.get('allow_negative_gas') is not True:
        raise SystemExit('ABSTAIN: FitSet must explicitly allow negative gas')
    paths = sorted(glob.glob(a.alpha))
    if len(paths) != 1: raise SystemExit('ABSTAIN: expected exactly one alpha file')
    rows = []
    from core.data_io import DataIO
    n = DataIO._count_alpha_trace_data_rows(paths[0])
    selected = [(paths[0], i) for i in range(n)]
    scans = load_selected_scans(selected)
    eng = OP.build_engine_from_config(cfg)
    fitter = DoasFitter(eng)
    candidate = select_candidate(FE.zero_base_policy_candidates(cfg, eng._wave_axis), cfg,
                                 shift_limit=a.shift_limit, squeeze_limit=a.squeeze_limit)
    starts = FE.stage1_policy_starts(candidate)['starts']
    callback = FE.production_stage1_callback(eng, fitter, cfg)
    policy_bounds = {axis: {'mode': 'INTERVAL', 'lower': float(spec['lower']),
                            'upper': float(spec['upper'])}
                     for axis, spec in candidate['policy'].items()}
    for row_index, scan in enumerate(scans):
        for start in starts:
            raw = callback(candidate, scan, start,
                           ref_props=cfg['ref_props'], policy_bounds=policy_bounds,
                           allow_negative_gas=True)
            rows.append({'row_index': row_index, 'start_id': start['id'], **raw})
    result = {'schema': 'CAESAR.FitExplorer.FullAlphaProfile.v1',
              'status': 'COMPLETE', 'limitations': ['No T2 verdict', 'No ranking', 'No Apply'],
              'candidate': candidate, 'planned_attempts': len(scans) * len(starts),
              'attempts': rows, 'source': {'fitset': os.path.basename(a.fitset),
              'alpha': os.path.basename(paths[0]), 'rows': len(scans)}}
    with open(a.output + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(result, fh, indent=2, sort_keys=True); fh.write('\n'); fh.flush(); os.fsync(fh.fileno())
    os.replace(a.output + '.tmp', a.output)
    print(json.dumps({'status': result['status'], 'attempts': len(rows), 'output': os.path.abspath(a.output)}))
    return 0

if __name__ == '__main__': raise SystemExit(main())
