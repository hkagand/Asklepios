/** Client for the agent service (agent/app.py), reached through the dev proxy at /api. */

export type Status = 'ok' | 'check' | 'unsourced' | 'unsupported' | 'plain'

export interface Segment {
  text?: string
  cite?: string[]
}

export interface Block {
  kind: 'paragraph' | 'bullet' | 'heading'
  level: number
  segments: Segment[]
  status: Status
  issues: string[]
}

export interface Step {
  tool: string
  label: string
}

export interface Answer {
  blocks: Block[]
  sources: Record<string, { label: string }>
  steps: Step[]
  elapsedMs: number
  model: string
}

export type AgentEvent = { type: 'step'; step: Step } | { type: 'answer'; answer: Answer } | { type: 'error'; message: string }

const NOT_RUNNING = 'The agent service is not reachable. Start it from the project folder with: python -m agent'

export async function agentHealth(signal: AbortSignal): Promise<{ model: string }> {
  const response = await fetch('/api/health', { signal })
  if (!response.ok) throw new Error(NOT_RUNNING)
  return (await response.json()) as { model: string }
}

/** Asks one question in a conversation and reports progress as server-sent events arrive. */
export async function ask(
  patientId: string,
  sessionId: string,
  question: string,
  onEvent: (event: AgentEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`/api/patients/${encodeURIComponent(patientId)}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, question }),
      signal,
    })
  } catch (error) {
    if (signal.aborted) throw error
    throw new Error(NOT_RUNNING, { cause: error })
  }
  if (!response.ok || !response.body) {
    throw new Error(response.status >= 500 ? NOT_RUNNING : `The agent service answered ${response.status} ${response.statusText}.`)
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += value
    let end: number
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const event = parseEvent(buffer.slice(0, end))
      buffer = buffer.slice(end + 2)
      if (event) onEvent(event)
    }
  }
}

function parseEvent(chunk: string): AgentEvent | undefined {
  let name = 'message'
  const data: string[] = []
  for (const line of chunk.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  if (data.length === 0) return undefined
  const payload: unknown = JSON.parse(data.join('\n'))
  if (name === 'step') return { type: 'step', step: payload as Step }
  if (name === 'answer') return { type: 'answer', answer: payload as Answer }
  if (name === 'error') return { type: 'error', message: (payload as { message: string }).message }
  return undefined
}
