"""Read screened native loads, including explicitly named low-fanout roots."""
import csv
from decimal import Decimal


def measured_table(path,explicit):
    result={}
    with path.open() as f:
        reader=csv.DictReader(f,delimiter='\t')
        assert reader.fieldnames==['net','driver','loads','pin_load_pf','limit_pf','missing_sink_caps']
        for row in reader:
            loads,missing=int(row['loads']),int(row['missing_sink_caps'])
            used,limit=Decimal(row['pin_load_pf']),Decimal(row['limit_pf'])
            assert loads>0 and (loads>=64 or explicit.get(row['net'])==loads)
            assert 0<=missing<=loads and used>=0 and limit>0
            assert used.is_finite() and limit.is_finite()
            assert row['net'] and row['driver'] and row['net'] not in result
            result[row['net']]={'driver':row['driver'],'loads':loads,'missing':missing,'pin_load_pf':used,'limit_pf':limit}
    assert result
    for net,expected in explicit.items():
        assert net in result and result[net]['loads']==expected
    return result
