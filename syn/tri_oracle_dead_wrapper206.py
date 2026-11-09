"""Authorize only the exhaustively audited, completely disconnected wrapper pins."""
def validate_dead_wrapper_pins(rows, reported, preserved, *, expected_count=32106):
    names=[row['pin'] for row in rows]
    if len(names)!=len(set(names)) or len(names)!=expected_count or set(names)!=set(reported):
        raise ValueError('Dead-wrapper audit identity/count mismatch')
    if set(names)&set(preserved):
        raise ValueError('Cleanup intersects preserved mapped-controller interface')
    for row in rows:
        if row['direction']!='in':raise ValueError('Cleanup target is not an input')
        for side in ['outer','inner']:
            if row[side+'_net'] or row[side+'_constant']:
                raise ValueError('Cleanup target still has a flat connection')
            for field in ['leaf_loads','top_loads','leaf_drivers','top_drivers']:
                if int(row[side+'_'+field])!=0:raise ValueError('Cleanup target has a live flat cone')
    return set(names)
