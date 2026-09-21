from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from collections.abc import Mapping
from types import MappingProxyType
from urllib.parse import urlparse

from .domain import (FHIR_RELEASE, SUPPORTED_BUNDLE_TYPES, SUPPORTED_RESOURCES,
    FhirBundle, FhirLimits, FhirReferenceError, FhirResource, FhirSecurityError,
    FhirSemanticError, FhirStructuralError, UnsupportedFhirResource)


def _depth(value, level=0):
    if not isinstance(value, (dict, list)): return level
    children = value.values() if isinstance(value, dict) else value
    return max((_depth(item, level + 1) for item in children), default=level)


def _timestamp(value):
    if value is None: return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise FhirStructuralError("invalid FHIR timestamp") from exc
    if parsed.tzinfo is None: raise FhirStructuralError("FHIR timestamp must contain timezone")
    return parsed


class FhirR4BundleParser:
    def __init__(self, limits=FhirLimits()): self._limits = limits

    def parse(self, payload: bytes, *, fhir_version: str) -> FhirBundle:
        if fhir_version != FHIR_RELEASE: raise FhirStructuralError("unsupported FHIR release")
        if not isinstance(payload, bytes): raise FhirStructuralError("FHIR input must be bytes")
        if len(payload) > self._limits.max_bundle_bytes: raise FhirSecurityError("FHIR Bundle exceeds byte limit")
        try: raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise FhirStructuralError("invalid FHIR JSON") from exc
        if not isinstance(raw, dict) or raw.get("resourceType") != "Bundle": raise FhirStructuralError("FHIR Bundle is required")
        if _depth(raw) > self._limits.max_nesting_depth: raise FhirSecurityError("FHIR nesting limit exceeded")
        bundle_id, bundle_type = raw.get("id"), raw.get("type")
        if not isinstance(bundle_id, str) or not bundle_id.strip(): raise FhirStructuralError("Bundle.id is required")
        if bundle_type not in SUPPORTED_BUNDLE_TYPES: raise FhirStructuralError("unsupported Bundle.type")
        entries = raw.get("entry", [])
        if not isinstance(entries, list) or not entries: raise FhirStructuralError("Bundle.entry is required")
        if len(entries) > self._limits.max_resources: raise FhirSecurityError("FHIR resource count limit exceeded")
        resources=[]
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict): raise FhirStructuralError("Bundle entry resource is required")
            item=entry["resource"]; kind=item.get("resourceType"); identifier=item.get("id")
            if kind not in SUPPORTED_RESOURCES: raise UnsupportedFhirResource(f"UNSUPPORTED_RESOURCE:{kind}")
            if not isinstance(identifier, str) or not identifier.strip(): raise FhirStructuralError("FHIR resource id is required")
            self._bounded_resource(item)
            meta=item.get("meta") or {}
            resources.append(FhirResource(kind,identifier,entry.get("fullUrl"),meta.get("versionId"),
                _timestamp(meta.get("lastUpdated")),MappingProxyType(item)))
        bundle=FhirBundle(bundle_id,bundle_type,fhir_version,tuple(resources),sha256(payload).hexdigest())
        FhirReferenceResolver(self._limits).validate(bundle)
        return bundle

    def _bounded_resource(self, item):
        if item["resourceType"] == "Observation" and len(item.get("component", ())) > self._limits.max_observation_components:
            raise FhirSecurityError("Observation component limit exceeded")
        if item["resourceType"] == "DiagnosticReport" and len(item.get("result", ())) > self._limits.max_diagnostic_results:
            raise FhirSecurityError("DiagnosticReport result limit exceeded")
        if item["resourceType"] == "DocumentReference":
            description=item.get("description", "")
            if not isinstance(description,str) or len(description)>self._limits.max_document_metadata_chars:
                raise FhirSecurityError("DocumentReference metadata limit exceeded")


class FhirReferenceResolver:
    def __init__(self, limits=FhirLimits()): self._limits=limits

    def validate(self,bundle):
        index={}; logical={}
        for resource in bundle.resources:
            if resource.logical_reference in logical: raise FhirReferenceError("duplicate logical identity")
            logical[resource.logical_reference]=resource
            for key in (resource.logical_reference,resource.full_url):
                if not key: continue
                if key in index: raise FhirReferenceError("ambiguous FHIR reference")
                index[key]=resource
        graph={item.logical_reference:[] for item in bundle.resources}
        for item in bundle.resources:
            for reference in self._references(item.data):
                target=index.get(reference)
                if target is None:
                    parsed=urlparse(reference)
                    if parsed.scheme in {"http","https"}: raise FhirSecurityError("external FHIR reference resolution is prohibited")
                    raise FhirReferenceError(f"unresolved FHIR reference:{reference}")
                graph[item.logical_reference].append(target.logical_reference)
        self._cycles(graph)
        clinical=SUPPORTED_RESOURCES-{"Patient","Practitioner","Organization"}
        for item in bundle.resources:
            if item.resource_type in clinical:
                field={"AllergyIntolerance":"patient","Coverage":"beneficiary"}.get(item.resource_type,"subject")
                subject=(item.data.get(field) or {}).get("reference")
                target=index.get(subject) if subject else None
                if target is None or target.resource_type!="Patient": raise FhirReferenceError("clinical resource requires Patient subject")
        return index

    @staticmethod
    def _references(value):
        found=[]
        def visit(node):
            if isinstance(node,Mapping):
                for key,item in node.items():
                    if key=="reference" and isinstance(item,str): found.append(item)
                    else: visit(item)
            elif isinstance(node,list):
                for item in node: visit(item)
        visit(value);return tuple(found)

    def _cycles(self,graph):
        def visit(node,path):
            if len(path)>self._limits.max_reference_depth: raise FhirReferenceError("FHIR reference depth exceeded")
            if node in path: raise FhirReferenceError("circular FHIR reference")
            for target in graph[node]: visit(target,path+(node,))
        for node in graph: visit(node,())
