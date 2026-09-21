from __future__ import annotations
from decimal import Decimal
from .domain import *

class InMemoryTerminologyRepository:
    def __init__(self):self._streams={}
    def append(self,stream_id,record):
        history=self._streams.setdefault(stream_id,[])
        if record in history:raise TerminologyVersionConflict("terminology record cannot be duplicated")
        history.append(record)
    def latest(self,stream_id):
        history=self.history(stream_id);return history[-1] if history else None
    def history(self,stream_id):return tuple(self._streams.get(stream_id,()))
    def search(self,term,code_system,version):
        key=term.casefold().strip();found=[]
        for records in self._streams.values():
            if not records or not isinstance(records[-1],ClinicalConcept):continue
            item=records[-1]
            terms={item.preferred_term.casefold(),item.display_name.casefold(),*(value.casefold() for value in item.synonyms),*(code.code.casefold() for code in item.codes)}
            if item.code_system is code_system and item.version==version and key in terms:found.append(item)
        return tuple(sorted(found,key=lambda item:item.canonical_id))
    def mappings(self,source_codes,target_system):
        source={(item.code_system,item.code,item.version) for item in source_codes};found=[]
        for records in self._streams.values():
            if not records or not isinstance(records[-1],ConceptMapping):continue
            item=records[-1];item_source={(code.code_system,code.code,code.version) for code in item.source_codes}
            if source==item_source and any(code.code_system is target_system for code in item.target_codes):found.append(item)
        return tuple(sorted(found,key=lambda item:item.mapping_id))
    def version(self,code_system,version):
        return next((records[-1] for records in self._streams.values() if records and isinstance(records[-1],TerminologyVersion) and records[-1].code_system is code_system and records[-1].version==version),None)

class InMemoryTerminologyAuditAdapter:
    def __init__(self):self._events=[]
    def append(self,event):
        if any(item.event_id==event.event_id for item in self._events):raise TerminologyVersionConflict("terminology audit is append-only")
        self._events.append(event)
    def history(self,subject_reference):return tuple(item for item in self._events if item.subject_reference==subject_reference)

class DeterministicUcumAdapter:
    def __init__(self,rules=()):self._rules={(item.source_unit,item.target_unit,item.ucum_version):item for item in rules}
    def normalize(self,value,unit,target_unit,version):
        value=Decimal(str(value))
        if unit==target_unit:return UnitNormalization(value,unit,value,target_unit,"UCUM identity conversion",version)
        rule=self._rules.get((unit,target_unit,version))
        if rule is None:raise UnknownUnitConversion("no validated UCUM conversion rule")
        return UnitNormalization(value,unit,value*rule.factor+rule.offset,target_unit,rule.provenance,version)

class InMemoryTerminologyMappingGovernanceRepository:
    def __init__(self):self._items={};self._references={}
    def append(self,value):
        if value.governance_record_id in self._items:raise TerminologyVersionConflict("mapping governance is append-only")
        stream=value.target_concept_id or "unmapped:"+value.source_reference;history=self.history_by_concept(stream);previous=history[-1] if history else None
        if (previous is None and (value.version!=1 or value.predecessor_record_id is not None)) or (previous and (value.version!=previous.version+1 or value.predecessor_record_id!=previous.governance_record_id)):raise TerminologyVersionConflict("invalid mapping governance predecessor")
        self._items[value.governance_record_id]=value
    def get(self,identifier):return self._items.get(identifier)
    def current_by_concept(self,concept_id):
        values=self.history_by_concept(concept_id);return values[-1] if values else None
    def history_by_concept(self,concept_id):return tuple(sorted((x for x in self._items.values() if (x.target_concept_id or "unmapped:"+x.source_reference)==concept_id),key=lambda x:x.version))
    def by_source_reference(self,source_reference):return tuple(x for x in self._items.values() if x.source_reference==source_reference)
    def reference_for(self,record):
        from uuid import uuid4
        from .governance import mapping_governance_integrity_hash
        if self.get(record.governance_record_id)!=record or record.integrity_hash!=mapping_governance_integrity_hash(record):raise InvalidTerminologyRecord("terminology governance record does not match canonical persistence")
        reference=PersistedTerminologyMappingGovernanceReference("tmr_"+uuid4().hex,record.governance_record_id,record.version,record.target_concept_id,record.terminology_version,record.source_reference,record.mapping_type,"SHARED_GLOBAL_REFERENCE",record.policy_version,record.integrity_hash,record.created_at)
        self._references[reference.reference_id]=reference;return reference
    def get_exact(self,reference):
        from .governance import mapping_governance_integrity_hash
        if not isinstance(reference,PersistedTerminologyMappingGovernanceReference) or self._references.get(reference.reference_id)!=reference:raise InvalidTerminologyRecord("owner-issued terminology governance reference is required")
        record=self.get(reference.governance_record_id)
        if record is None or (record.version,record.target_concept_id,record.terminology_version,record.source_reference,record.mapping_type,record.policy_version,record.integrity_hash)!=(reference.record_version,reference.target_concept_id,reference.terminology_version,reference.source_reference,reference.mapping_type,reference.policy_version,reference.integrity_hash) or record.integrity_hash!=mapping_governance_integrity_hash(record):raise InvalidTerminologyRecord("terminology governance reference mismatch")
        return record
