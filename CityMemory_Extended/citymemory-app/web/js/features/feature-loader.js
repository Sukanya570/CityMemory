/* Loads optional feature modules after the stable CityMemory core has initialized. */
(async function () {
  "use strict";
  const paths = Array.isArray(window.CITYMEMORY_FEATURES) ? window.CITYMEMORY_FEATURES : [];
  for (const path of paths) {
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = path;
      script.onload = resolve;
      script.onerror = () => reject(new Error("Could not load CityMemory feature: " + path));
      document.body.appendChild(script);
    }).catch(error => console.error(error));
  }
  if (window.CityMemoryExtensions) {
    window.CityMemoryExtensions.emit("extensions:ready", {
      features: window.CityMemoryExtensions.listFeatures()
    });
  }
})();
