import { ClipboardIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"

type RevealedApiKeyDialogProps = {
  value?: string
  copiedValue: string | null
  onCopy: (value: string) => void
  onClose: () => void
}

export function RevealedApiKeyDialog({
  value,
  copiedValue,
  onCopy,
  onClose,
}: RevealedApiKeyDialogProps) {
  return (
    <Dialog open={Boolean(value)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>API key created</DialogTitle>
          <DialogDescription>
            This raw key is returned once. Store it before closing this dialog.
          </DialogDescription>
        </DialogHeader>
        {value ? (
          <Field>
            <FieldLabel htmlFor="new-api-key">Raw key</FieldLabel>
            <Input id="new-api-key" value={value} readOnly />
          </Field>
        ) : null}
        <DialogFooter>
          {value ? (
            <Button variant="outline" size="sm" onClick={() => onCopy(value)}>
              <ClipboardIcon data-icon="inline-start" />
              {copiedValue === value ? "Copied" : "Copy"}
            </Button>
          ) : null}
          <Button onClick={onClose}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
