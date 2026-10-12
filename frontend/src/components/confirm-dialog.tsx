import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"

/** Confirmation for destructive or irreversible actions. Returns a hook-friendly API. */
export function useConfirm() {
  const [state, setState] = useState<null | {
    title: string
    description: React.ReactNode
    confirmLabel: string
    destructive: boolean
    resolve: (ok: boolean) => void
  }>(null)

  const confirm = (opts: { title: string; description: React.ReactNode; confirmLabel?: string; destructive?: boolean }) =>
    new Promise<boolean>((resolve) =>
      setState({ confirmLabel: "Confirm", destructive: true, ...opts, resolve }))

  const close = (ok: boolean) => {
    state?.resolve(ok)
    setState(null)
  }

  const dialog = (
    <Dialog open={!!state} onOpenChange={(open) => !open && close(false)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{state?.title}</DialogTitle>
          <DialogDescription asChild>
            <div className="text-sm text-muted-foreground">{state?.description}</div>
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>Cancel</Button>
          <Button variant={state?.destructive ? "destructive" : "default"} onClick={() => close(true)} autoFocus>
            {state?.confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )

  return { confirm, dialog }
}
