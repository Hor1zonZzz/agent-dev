from phoenix.otel import register
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

# configure the Phoenix tracer
tracer_provider = register(
    project_name="agents",  # Default is 'default'
    auto_instrument=False,
)

OpenAIAgentsInstrumentor().instrument(tracer_provider=tracer_provider)
