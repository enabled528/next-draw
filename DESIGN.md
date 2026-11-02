# Next Draw Design

Reference: [Tesla design language](https://getdesign.md/tesla/design-md). This is a brief-based interpretation, not a pixel-exact clone. The approved product is the usable experiment itself, not a marketing page.

## Composition

- A black, full-viewport surface; NEXT DRAW identity at the upper left.
- One unframed work area with a stable number/result region above a lower-middle split action.
- Main action: `预测下一期号码`. The adjacent chevron selects the lottery. No navigation, cards, gradients, stock imagery or decorative backgrounds.
- Results use plain, large, tabular figures. Only the SSQ back number is blue.
- Secondary run details are an unframed definition list, opened through an information icon.

## Tokens

| Token | Value |
| --- | --- |
| Background | `#000000` |
| Foreground / primary button | `#f5f5f5` |
| Primary button text | `#111111` |
| Secondary text | `#999999` |
| Quiet text / divider | `#737373` / `#333333` |
| SSQ blue number | `#4c9aff` |
| Typeface | Helvetica Neue, Arial, PingFang SC, system sans-serif |
| Letter spacing | `0` |
| Button | 420px maximum width, 64px height; mobile 60px |
| Button / menu radius | 3px |
| Desktop numbers | 62px, fixed 66px tracks |
| Tablet numbers <=800px | 42px, fixed 46px tracks |
| Mobile numbers | 28px, fixed 32px tracks; 25px / 28px at <=360px |

## Motion And States

- A real queued/running job shows an indeterminate 650ms linear ring. No fabricated percentage.
- Stage descriptions cross-fade with opacity transitions: 120ms outgoing delay, 160ms transition. Space is reserved to prevent layout movement.
- Menu: 180ms ease-out opacity with a small 0.97 scale and 4px offset; transform origin is the trigger side. Keyboard opening has no entrance motion.
- Press feedback: scale 0.975 over 120ms. Result entrance: 220ms opacity.
- Reduced motion removes rotation and transforms; task status remains visible as text.
- Hover styles apply only to a fine pointer with hover support. All icon controls have names and hover titles.
- Idle, queued, working, success, below-threshold, cached-data warning, failed, cancelling, cancelled and disconnected states are explicit.

## Accessibility And Layout

- Semantic buttons and menu radio items; arrows, Home/End, Escape and focus return supported.
- Live progress region, visible keyboard focus, disabled unverified QXC entry with its reason.
- Stable result, action and progress dimensions; 320px minimum viewport. No viewport-scaled fonts.
- Large result figures are the primary visual asset: the actual generated state remains readable without decorative media.
