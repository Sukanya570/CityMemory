/* CityMemory extension API.
 * Optional feature scripts can subscribe to events and read a safe asset snapshot.
 * Keep core application state private; extensions should not mutate records directly.
 */
(function (global) {
  "use strict";
  const listeners = new Map();
  const registered = new Set();
  let context = {};

  function on(eventName, handler) {
    if (typeof handler !== "function") throw new TypeError("Extension handler must be a function.");
    if (!listeners.has(eventName)) listeners.set(eventName, new Set());
    listeners.get(eventName).add(handler);
    return function unsubscribe() {
      const group = listeners.get(eventName);
      if (group) group.delete(handler);
    };
  }

  function emit(eventName, payload) {
    const group = listeners.get(eventName);
    if (!group) return;
    [...group].forEach(handler => {
      try { handler(payload); }
      catch (error) { console.error("[CityMemory extension]", eventName, error); }
    });
  }

  function register(feature) {
    if (!feature || !feature.id || typeof feature.init !== "function") {
      throw new Error("A feature must provide an id and init(api) function.");
    }
    if (registered.has(feature.id)) {
      console.warn("[CityMemory] Duplicate feature ignored:", feature.id);
      return false;
    }
    registered.add(feature.id);
    try { feature.init(api); }
    catch (error) { console.error("[CityMemory] Feature failed to initialize:", feature.id, error); }
    emit("feature:registered", { id: feature.id, version: feature.version || "unspecified" });
    return true;
  }

  const api = {
    on,
    emit,
    register,
    setContext(value) { context = value || {}; },
    getContext() { return context; },
    listFeatures() { return [...registered]; }
  };

  global.CityMemoryExtensions = api;
})(window);
