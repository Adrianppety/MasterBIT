# Popup Design Plan

## Subject Matter
Pokémon Trading Card Game pack opening interface - informing users when pack data has issues but cards are still available.

## Audience
Pokémon TCG players/collectors using the pack opening feature.

## Primary Job
Clearly communicate data issues in a way that doesn't alarm users but maintains trust in the system.

## Design Plan

### Color Palette
- Background: #1A1A2E (deep blue-black, reminiscent of card backs)
- Primary Accent: #FF6B35 (vibrant orange-red, like energy symbols)
- Secondary Accent: #4ECDC4 (teal/cyan, like water energy)
- Text: #FFFFFF (white for contrast)
- Success/Info: #A8E6CF (light green, for positive message that cards are there)
- Border/Shadow: rgba(255, 107, 53, 0.3) (semi-transparent accent)

### Typography
- Headline/Title: 'Pokemon Solid' (if available) or 'Press Start 2P' - retro gaming font that evokes TCG feel without being literal
- Body: 'Inter' or 'Roboto' - clean, highly readable sans-serif for clarity
- Type Scale: 
  - Title: 1.5rem (24px) bold
  - Body: 1rem (16px) regular
  - Button: 0.9rem (14px) medium

### Layout Concept
```
+--------------------------------------------------+
|                                                  |
|                                                  |
|              [CARD ICON]                         |
|                                                  |
|      ATENÇÃO: PACOTES COM DADOS INCOMPLETOS     |
|                                                  |
|   Alguns pacotes não tiveram valores possíveis   |
|   de serem colocados, mas as cartas estão lá!    |
|                                                  |
|                                                  |
|              [ ENTENDIDO ]                       |
|                                                  |
|                                                  |
+--------------------------------------------------+
```
- Centered modal/popup with slight elevation
- Card icon (simplified Pokéball or card stack) above message
- Message in Portuguese as requested
- Single action button at bottom
- Padding: 2rem on all sides
- Border radius: 16px (softer than default)
- Box shadow: 0 8px 32px rgba(0,0,0,0.4)

### Principles
1. **Clarity over creativity**: Message must be immediately understandable
2. **Pokémon TCG essence**: Uses colors and typography that hint at the game without being literal character copies
3. **Calm urgency**: Alert is noticeable but not alarming - uses warm accent rather than red warning colors
4. **Tactile feel**: Slight elevation and rounded corners make it feel like a physical card
5. **Minimalist**: Only essential elements - no decorative fluff that distracts from message