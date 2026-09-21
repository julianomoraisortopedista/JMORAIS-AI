from .domain import *
def canonical_templates():
    def make(kind,sections):
        allowed=[]
        for section in sections:
            sources={"clinical":(SourceType.PATIENT_CLINICAL_STATE,SourceType.TERMINOLOGY),"orthopedic":(SourceType.ORTHOPEDIC_ASSESSMENT_SET,SourceType.TERMINOLOGY),"evidence":(SourceType.GOVERNED_EVIDENCE,SourceType.CANONICAL_VANCOUVER),"guidelines":(SourceType.GUIDELINE_RECOMMENDATION_SET,),"limitations":()}.get(section,(SourceType.PATIENT_CLINICAL_STATE,))
            allowed.append((section,sources))
        return DocumentTemplate("template:"+kind.value.lower(),kind,"1.0",sections,sections,(),tuple(allowed),("DETERMINISTIC","NO_FILLER","SOURCE_ATTRIBUTION"),"MIP-08.1")
    mapping={
      DocumentType.CLINICAL_REPORT:("clinical","limitations"),DocumentType.MEDICAL_SUMMARY:("clinical","limitations"),DocumentType.FOLLOW_UP_REPORT:("clinical","limitations"),DocumentType.SURGICAL_HISTORY_SUMMARY:("clinical","limitations"),DocumentType.ORTHOPEDIC_ASSESSMENT_REPORT:("orthopedic","evidence","guidelines","limitations"),DocumentType.EVIDENCE_SUMMARY:("evidence","limitations"),DocumentType.GUIDELINE_SUMMARY:("guidelines","limitations"),DocumentType.PROCEDURE_JUSTIFICATION_DRAFT:("clinical","orthopedic","evidence","guidelines","limitations"),DocumentType.AUDIT_SUPPORT_DRAFT:("clinical","orthopedic","evidence","guidelines","limitations")}
    return tuple(make(kind,sections) for kind,sections in mapping.items())
