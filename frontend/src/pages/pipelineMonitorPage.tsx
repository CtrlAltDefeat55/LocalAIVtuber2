import PipelineDebugger from "@/components/pipeline-debugger"
import { PageBody, PageHeader } from "@/components/layout"
import { SquareActivity } from "lucide-react"

function PipelineMonitorPage() {
    return (
        <PageBody wide>
            <PageHeader icon={SquareActivity} title="Pipeline"
                description="Each message flows through the brain (text), the voice (audio) and playback. Use this to see where a reply is waiting." />
            <PipelineDebugger />
        </PageBody>
    )
}

export default PipelineMonitorPage
