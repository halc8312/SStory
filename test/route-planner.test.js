const test = require('node:test');
const assert = require('node:assert/strict');
const fixture = require('../tests/fixtures/route-planner-cases.json');
const planner = require('../docs/assets/js/route-planner.js');

test('browser planner excludes every non-operational status', () => {
  for (const status of ['forbidden', 'experimental', 'dangerous', 'closed']) {
    const route = fixture.routes.find(candidate => candidate.status === status);
    assert.equal(planner.evaluateRoute(route).allowed, false, status);
  }
  assert.equal(planner.evaluateRoute(fixture.routes.find(route => route.status === 'restricted')).allowed, false);
  assert.equal(
    planner.evaluateRoute(fixture.routes.find(route => route.status === 'restricted'), { allowRestricted: true }).allowed,
    true
  );
});

test('browser planner applies seasonal status and month rules', () => {
  const seasonal = fixture.routes.find(route => route.status === 'seasonal');
  assert.equal(planner.evaluateRoute(seasonal, { month: 7 }).allowed, true);
  assert.equal(planner.evaluateRoute(seasonal, { month: 1 }).allowed, false);
  const unknownMonth = planner.evaluateRoute(seasonal);
  assert.equal(unknownMonth.allowed, true);
  assert.equal(unknownMonth.warnings.length, 1);
});

test('browser planner uses the same weight contract as the Python planner', () => {
  const active = fixture.routes.find(route => route.id === 'active_ab');
  assert.equal(planner.computeRouteCost(active, 'time'), 4);
  assert.equal(planner.computeRouteCost(active, 'distance'), 40);
  assert.equal(planner.computeRouteCost(active, 'safety'), 16);
  assert.equal(planner.computeRouteCost(active, 'cost'), 10);

  const subminimum = {
    id: 'subminimum',
    from: 'a',
    to: 'b',
    estimated_time_hours: 0.05,
    distance_km: 0.05,
    cost_gold: 0.05,
    danger_level: 0
  };
  const { graph } = planner.buildGraph(fixture.nodes, [subminimum]);
  assert.equal(graph.a[0].cost, planner.MINIMUM_EDGE_COST);
});

test('browser planner never chooses forbidden shortcut and enforces seasonal availability', () => {
  const summer = planner.findRoute({
    ...fixture,
    fromId: 'a',
    toId: 'c',
    weight: 'time',
    month: 7
  });
  assert.equal(summer.found, true);
  assert.deepEqual(summer.segments.map(segment => segment.route.id), ['active_ab', 'seasonal_bc']);

  const winter = planner.findRoute({ ...fixture, fromId: 'a', toId: 'c', month: 1 });
  assert.equal(winter.found, false);
});
