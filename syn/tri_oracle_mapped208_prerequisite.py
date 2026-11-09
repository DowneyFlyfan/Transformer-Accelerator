"""Bind a positive mapped run to its completed same-source wrong-reference control."""
def require_wrong_reference(record, static_sources, workers):
    assert record['state']=='expected_wrong_mapped_reference_rejected'
    assert record['negative_reference'] is True
    assert type(record['native_exit_status']) is int and record['native_exit_status']!=0
    assert record['requested_simulation_workers']==workers
    assert record['temporary_build_removed'] is True
    assert static_sources
    assert all(record['source_sha256'].get(path)==digest for path,digest in static_sources.items()), 'Negative control used different source/tool/models'
