import { Stream } from "@/components/stream"
import { PageBody, PageHeader } from "@/components/layout"
import { Badge } from "@/components/ui/badge"
import { Radio } from "lucide-react"

function StreamPage() {
    return (
        <PageBody wide>
            <PageHeader icon={Radio} title="Stream"
                description="Read YouTube live chat and run karaoke setlists."
                actions={<Badge variant="outline" className="border-warning/50 text-warning">Experimental</Badge>} />
            <Stream />
        </PageBody>
    )
}

export default StreamPage
