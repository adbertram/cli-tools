# BrickLink Item Dimensions Reference

Sources:
- https://www.bricklink.com/help.asp?viewType=shop&helpID=2510 (last updated Feb 5, 2026)
- https://www.bricklink.com/help.asp?helpID=261 (last updated Mar 10, 2024)

## Two Dimension Systems for Parts

BrickLink maintains **two separate dimension systems** for parts. Understanding the difference is critical for volume calculations.

### 1. Stud Dimensions (Modular Dimensions)

- **Units**: Studs (horizontal) and bricks (vertical)
- **API fields**: `dim_x`, `dim_y`, `dim_z` (returned by catalog API)
- **Field order**:
  - `dim_x` = Depth in studs (shortest of two primary dimensions)
  - `dim_y` = Width in studs (longest of two primary dimensions)
  - `dim_z` = Height in bricks
- **Z can be zero**: Parts less than one brick high correctly have `dim_z = 0`
- **Not all parts have stud dims**: "Unusually shaped parts as a rule are not assigned stud dimensions"
- **Conversion to cm**: 1 stud = 0.8 cm horizontal, 1 brick = 1.05 cm vertical (approximate)
- **Organic/irregular shapes** may have no stud dims at all — only parts where dims "can easily be perceived by counting studs and bricks" get stud dims
- **Field order convention**: Width x Length x Height (Width = shorter, Length = longer), but exceptions exist:
  - Slopes: first dimension is the direction of the slope (e.g., Slope 33 **3** x 1 = 3 along the slope)
  - Some parts use Length x Width x Height for sorting/naming consistency
- **Height = 0 means less than 1 brick**: Plates, tiles, and other sub-brick-height parts have `dim_z = 0`. A plate is 1/3 brick height. For DUPLO, a plate is 1/2 brick height.
- **Height often omitted from names**: Standard-height parts omit height in their name (e.g., "Brick 2 x 4" implies height = 1)
- **Different scales exist**: DUPLO, Primo, Explore, and Modulex have different base units. The stud dim system uses the base unit of that line (e.g., DUPLO stud dims are based on DUPLO brick size, not System brick size).

**Examples**:

| Part | dim_x | dim_y | dim_z | Stud Notation |
|------|-------|-------|-------|---------------|
| Brick 2 x 4 | 2 | 4 | 1 | 2 x 4 x 1 (M) |
| Slope 33 3 x 1 | 3 | 1 | 1 | 3 x 1 x 1 (M) |
| Brick, Modified Facet 4 x 4 | 4 | 4 | 1 | 4 x 4 x 1 (M) |
| Sunglasses with Pin | ? | ? | ? | ? (M) |

### 2. Packing Dimensions

- **Units**: Centimeters (actual physical measurements)
- **Purpose**: Used by BrickLink Instant Checkout to calculate shipping costs
- **Field order**: Same as stud dimensions for parts that have stud dims; any order for parts without
- **All three values must be positive** (unlike stud dims where z can be 0)
- **Not available via standard catalog API** (separate from stud dims)

**Examples**:

| Part | x (cm) | y (cm) | z (cm) |
|------|--------|--------|--------|
| Brick 2 x 4 | 1.6 | 3.2 | 1.15 |
| Slope 33 3 x 1 | 2.4 | 0.8 | 1.15 |
| Brick, Modified Facet 4 x 4 | 1.1 | 4.5 | 1.15 |
| Sunglasses with Pin | 0.5 | 0.5 | 1.1 |

### Packing Type (Parts Only)

Parts have a Packing Type setting with two options:
- **Weight Bound**: For parts approximately 2 x 2 x 2 cm and smaller
- **Volume Bound**: For large or unusually shaped parts (e.g., sticker sheets)

On the catalog detail page, Volume Bound packing dimensions are distinguished by the letter **V**.

## Stud Dims vs Packing Dims: Why It Matters

Stud dimensions represent a **modular grid bounding box**, not the actual physical volume. This causes significant overestimation for:
- **Thin/flat parts**: e.g., Technic Link 1x9 Bent (64451) has stud dims 5x7x1 but physically only ~1 stud wide
- **Irregular/bent parts**: Bounding box includes all empty space around the bend
- **Wedge/slope parts**: Triangular shapes occupy far less than their rectangular bounding box

Packing dimensions are actual cm measurements and far more accurate for volume calculations.

## Dimensions by Item Type

### Sets
- **Units**: Centimeters
- **Fields**: x = Width, y = Height, z = Depth
- Must be based on actual physical item, not dealer catalogs

### Minifigures
- **Units**: Centimeters
- **Fields**: x = Width, y = Height, z = Depth
- Y is almost always the largest (taller than wide)
- Extended features should be reduced with minimal disassembly before measuring

### Instructions
- **Units**: Centimeters
- **Fields**: x = Width, y = Height, z = Thickness
- Multiple booklets: stack efficiently and measure the stack
- Folded instructions: use folded dimensions

### Books
- **Units**: Centimeters
- **Fields**: x = Width, y = Height, z = Thickness
- Leaflet-form books: Item Dimensions = unfolded, Packing Dimensions = folded

### Catalogs
- **Units**: Centimeters
- **Fields**: x = Width, y = Height, z = Thickness
- Two dimension sets: Item Dimensions (as shown in image) and Packing Dimensions (as originally folded)
- Large catalogs typically only have Item Dimensions (never folded)

### Empty Boxes
- **Units**: Centimeters
- Duplicates set dimensions
- Additional "Flat Dimensions" field for flattened boxes
- Rigid boxes that can't be flattened should not have Flat Dimensions

### Gear
- Measure like the most similar standard item type (set, book, etc.)
- Two dimension fields: main (as shown in image) and optimized for shipping
- Always treated as Volume Bound by Instant Checkout