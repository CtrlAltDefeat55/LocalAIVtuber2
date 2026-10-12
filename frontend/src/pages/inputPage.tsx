import VoiceStreamer from "@/components/voice-streamer"
import { PageBody, PageHeader } from "@/components/layout"
import { Mic } from "lucide-react"

function InputPage() {
    return (
        <PageBody>
            <PageHeader icon={Mic} title="Microphone"
                description="Talk to your VTuber out loud. Speech is detected and transcribed on this computer, then sent as a message. The speech model downloads on first use." />
            <VoiceStreamer />
        </PageBody>
    )
}

export default InputPage
