from .domain import *
class InMemoryPromptRepository:
    def __init__(self):self._items={};self._streams={}
    def append(self,value):
        if value.prompt_version_id in self._items:raise PromptVersionConflict("prompt history is append-only")
        history=self.history(value.template_id)
        if history and (value.version!=history[-1].version+1 or value.previous_version_id!=history[-1].prompt_version_id):raise PromptVersionConflict("invalid prompt version chain")
        if not history and (value.version!=1 or value.previous_version_id is not None):raise PromptVersionConflict("prompt history must begin at version 1")
        self._items[value.prompt_version_id]=value;self._streams.setdefault(value.template_id,[]).append(value.prompt_version_id)
    def get(self,identifier):return self._items.get(identifier)
    def history(self,template_id):return tuple(self._items[x] for x in self._streams.get(template_id,()))
class InMemoryPromptAuditRepository:
    def __init__(self):self._items=[]
    def append(self,event):
        if any(x.event_id==event.event_id for x in self._items):raise PromptVersionConflict("prompt audit is append-only")
        self._items.append(event)
    def history(self,request_id):return tuple(x for x in self._items if x.request_id==request_id)
    def history_by_correlation(self,correlation_id):return tuple(x for x in self._items if x.correlation_id==correlation_id)
class InMemoryInvocationRepository:
    def __init__(self):self._items=[]
    def append(self,value):
        if any(x.invocation_id==value.invocation_id for x in self._items):raise PromptVersionConflict("invocation history is append-only")
        self._items.append(value)
    def history(self,request_id):return tuple(x for x in self._items if x.request_id==request_id)
    def history_by_correlation(self,correlation_id):return tuple(x for x in self._items if x.correlation_id==correlation_id)
class InMemoryLLMInvocationContextRepository:
    def __init__(self):self._items={}
    def append(self,value):
        if not isinstance(value,LLMInvocationContext):raise LLMPolicyRejected("trusted invocation context is required")
        if value.request_id in self._items:raise PromptVersionConflict("invocation context is append-only")
        self._items[value.request_id]=value
    def get(self,request_id):return self._items.get(request_id)
    def history_by_correlation(self,correlation_id):return tuple(x for x in self._items.values() if x.correlation_id==correlation_id)
    def status(self,request_id):return InvocationContextPersistenceStatus.PERSISTED if request_id in self._items else InvocationContextPersistenceStatus.LEGACY_MISSING_INVOCATION_CONTEXT
class MockProviderAdapter:
    provider=LLMProvider.MOCK
    def __init__(self,responses):self._responses=list(responses);self.requests=[]
    def invoke(self,request):
        self.requests.append(request)
        if not self._responses:raise LLMProviderFailure("mock provider exhausted")
        value=self._responses.pop(0)
        if isinstance(value,Exception):raise value
        return value
class TransportProviderAdapter:
    provider=None
    def __init__(self,transport):self._transport=transport
    def invoke(self,request):return self._transport.send(self.provider,request)
class OpenAIProviderAdapter(TransportProviderAdapter):provider=LLMProvider.OPENAI
class AzureOpenAIProviderAdapter(TransportProviderAdapter):provider=LLMProvider.AZURE_OPENAI
class AnthropicProviderAdapter(TransportProviderAdapter):provider=LLMProvider.ANTHROPIC
class GeminiProviderAdapter(TransportProviderAdapter):provider=LLMProvider.GOOGLE_GEMINI
class LocalModelProviderAdapter(TransportProviderAdapter):provider=LLMProvider.LOCAL
