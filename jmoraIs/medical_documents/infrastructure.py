from .domain import *
class InMemoryMedicalDocumentRepository:
    def __init__(self):self._streams={};self._ids=set()
    def append(self,value):
        if value.version_id in self._ids:raise DocumentVersionConflict("document history is append-only")
        history=self.history(value.document_stream_id)
        if history and (value.version!=history[-1].version+1 or value.previous_version_id!=history[-1].version_id):raise DocumentVersionConflict("invalid document version chain")
        if not history and (value.version!=1 or value.previous_version_id is not None):raise DocumentVersionConflict("document history must begin at version 1")
        self._ids.add(value.version_id);self._streams.setdefault(value.document_stream_id,[]).append(value)
    def latest(self,stream_id):
        values=self.history(stream_id);return values[-1] if values else None
    def history(self,stream_id):return tuple(self._streams.get(stream_id,()))
class InMemoryDocumentTemplateRepository:
    def __init__(self,items):self._items=tuple(items)
    def get(self,document_type,version=None):
        values=[x for x in self._items if x.document_type is document_type and (version is None or x.template_version==version)]
        return sorted(values,key=lambda x:x.template_version)[-1] if values else None
class InMemoryDocumentAuditAdapter:
    def __init__(self):self._items=[]
    def append(self,event):
        if any(x.event_id==event.event_id for x in self._items):raise DocumentVersionConflict("document audit is append-only")
        self._items.append(event)
    def history(self,stream_id):return tuple(x for x in self._items if x.document_stream_id==stream_id)
class InMemoryFactQueryAdapter:
    def __init__(self,items):self._items=items
    def facts(self,state_reference_id):return tuple(self._items.get(state_reference_id,()))
class InMemoryReferenceQueryAdapter:
    def __init__(self,items,key):self._items={getattr(x,key):x for x in items}
    def get(self,identifier):return self._items.get(identifier)
class InMemoryLatestQueryAdapter:
    def __init__(self,value):self.value=value
    def latest(self,subject_reference):return self.value
