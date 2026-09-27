const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script); // Check syntax of the full script used by the page.
const start = script.indexOf('function h01(');
const end = script.indexOf('function pageStarSVG(');
const context = vm.createContext({});
vm.runInContext(script.slice(start, end), context);
const geometry = entry => JSON.parse(JSON.stringify(context.constellationGeometry(entry)));
const seeds = entry => Array.from(context.starSeeds(entry));
const lineCount = shape => (shape.pathData.match(/L/g) || []).length;
const freeze = value => {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
};

const publicPath = path.join(root, 'entries.json');
const publicBytes = fs.readFileSync(publicPath);
const entries = freeze(JSON.parse(publicBytes));
for (const entry of entries) {
  const before = JSON.stringify(entry);
  const shape = geometry(entry);
  assert.ok(shape.pts.length >= 4 && shape.pts.length <= 8);
  assert.equal(lineCount(shape), shape.pts.length - 1);
  assert.deepEqual(geometry(entry), shape);
  assert.deepEqual(geometry({...entry, name: 'changed label', diary: 'changed label'}), shape);
  assert.equal(JSON.stringify(entry), before);
}

for (const count of [1, 2, 3]) {
  const entry = freeze({date: '2026-09-27', hoshi: Array.from({length: count}, (_, i) => 'test-token-' + i)});
  const shape = geometry(entry);
  assert.ok(shape.pts.length >= 4 && shape.pts.length <= 8);
  assert.equal(lineCount(shape), shape.pts.length - 1);
  assert.equal(entry.hoshi.length, count);
  assert.deepEqual(geometry(entry), shape);
}
assert.notDeepEqual(geometry({hoshi: ['first']}), geometry({hoshi: ['second']}));

const demos = freeze(JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/entries.demo.json'), 'utf8')));
for (const entry of demos) {
  assert.deepEqual(seeds(entry), Array.from({length: entry.stars}, (_, i) => entry.date + ':' + i));
  assert.equal(geometry(entry).pts.length, entry.stars);
  assert.equal(lineCount(geometry(entry)), entry.stars - 1);
}
assert.equal(geometry({date: '2026-09-27', stars: 0}).pts.length, 0);
assert.deepEqual(fs.readFileSync(publicPath), publicBytes);
assert.ok(!html.includes('点はその日の出来事の数'));
console.log(JSON.stringify({status: 'passed', publicEntries: entries.length,
  productionPoints: entries.map(entry => geometry(entry).pts.length),
  demoEntriesPreserved: demos.length, sourceCountsChecked: [1, 2, 3]}, null, 2));
