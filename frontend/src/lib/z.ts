/**
 * Centralized z-index scale.
 *
 * Pre-this module, the codebase had a mix of `z-10`, `z-20`, `z-30`,
 * `z-40`, `z-50`, and literal `z-[100]` scattered across surfaces, with
 * no rule for who beats whom. That meant two simultaneously-open
 * overlays (e.g. a workflow node config drawer + a freshly-opened
 * Dialog) could stack the wrong way and re-implement priority by
 * accident. Anything new should import from here.
 *
 * Layers (low to high):
 *
 *   sticky     — sticky table headers, the sidebar's pinned brand
 *                lockup, etc. Bumps content above the page background
 *                but below any local popover.
 *   dropdown   — popovers, menus, and other intra-page overlays
 *                anchored to a trigger. They should occlude the page
 *                content but defer to a global modal.
 *   overlay    — non-modal full-screen layers, e.g. the mobile palette
 *                slide-in's backdrop, where the user can still
 *                interact with off-canvas affordances.
 *   modal      — Dialog / Sheet / AlertDialog. Anything that owns
 *                focus and locks scroll. This is the "everything else
 *                stays below" tier.
 *   toast      — Sonner toasts, snackbars. Must occlude even modals
 *                so a save-success toast doesn't get hidden behind
 *                the dialog the save happened in.
 *
 * Don't introduce `z-[…]` arbitrary values in new code. If you need a
 * layer between these, add it here and document the reason.
 */
export const Z = {
  sticky: 20,
  dropdown: 30,
  overlay: 40,
  modal: 50,
  toast: 60,
} as const;

export type ZLayer = keyof typeof Z;
