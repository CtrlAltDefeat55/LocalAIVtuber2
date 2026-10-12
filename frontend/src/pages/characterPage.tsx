import { CharacterRender } from "@/components/character-render"

function CharacterPage({ isActive }: { isActive: boolean }) {
    return (
        <div className="h-full w-full">
            {/* rendering pauses while another page is open, so the GPU stays free */}
            <CharacterRender isActive={isActive} />
        </div>
    )
}

export default CharacterPage
