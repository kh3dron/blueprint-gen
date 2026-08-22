Factorio recipe tools

- [x] 01: recipe calculator
  - [x] for a given item, calculate the rates of all intermediate parts

- [x] 02: visualize blueprints

- [ ] compile designs into blueprints

- [ ] get game sprites
- [ ] get game fact tables
- [ ] DFS solver

Now we're going to enhance the funcionality of a basic blueprint, by treating them as objects with inputs and outputs.

Ideas for implementation:

- something akin to structure blocks in minecraft: every blueprint should have INPUT and OUTPUT points. in early blueprints, these will all be along the bottom edge of the builds; the first input being at the bottom left corner and the first output being on the bottom right corner. we may need to create modded versions of belts, to represent "belt with iron plate on left side", which might be an input in a gear blueprint; the assemblers will be assemblers with that recipe set, and the output belts may be "belt with iron gear on right side".

the end state here will be be meing able to request a blueprint that creates an object
