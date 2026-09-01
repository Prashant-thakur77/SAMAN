import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function Copilot() {
  return (
    <div className="space-y-8">
      <PageHeader
        section="Tools"
        title="Copilot"
        description="Ask about the material master in plain language. Answers cite their source rows and expose the query behind them; free-form SQL is never executed."
      />
      <MilestonePending
        what="The Copilot answers from retrieval plus whitelisted query templates, and upgrades transparently when a local Ollama model is available."
        milestone="M6"
      />
    </div>
  )
}
