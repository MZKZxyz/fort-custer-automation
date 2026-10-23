// Trusted QA oracle: install outside worker/candidate-writable storage.
// Run only in the independently isolated QA guest.
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const root = resolve(process.argv[2]);
const { directions, compile, initialState, transition } = await import(
  pathToFileURL(resolve(root, 'tools/maze-analyzer/solver.js')).href);
const expected = { up: [-1, 0], down: [1, 0], left: [0, -1], right: [0, 1] };
assert.deepEqual(directions, expected);
assert.ok(Object.isFrozen(directions));
for (const [name, delta] of Object.entries(expected)) {
  assert.ok(Object.isFrozen(directions[name]), name);
  for (let index = 0; index < 2; index++) {
    assert.throws(() => { directions[name][index] = 99; }, TypeError);
  }
  assert.throws(() => directions[name].push(99), TypeError);
  assert.throws(() => { directions[name] = [99, 99]; }, TypeError);
  assert.deepEqual(directions[name], delta);
}
const maze = compile(['   ', ' S ', ' E ']), state = initialState(maze);
for (const [name, pos] of Object.entries({ up: 1, down: 7, left: 3, right: 5 })) {
  assert.equal(transition(maze, state, name).pos, pos, name);
}
for (const name of ['toString', 'constructor', '__proto__', '', 'diagonal']) {
  assert.equal(transition(maze, state, name), null);
}
assert.deepEqual(state, initialState(maze));
console.log('direction-vector oracle passed');
