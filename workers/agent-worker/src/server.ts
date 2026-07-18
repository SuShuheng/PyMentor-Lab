/** Production Worker entrypoint: health, RedisSaver, BullMQ, and bounded shutdown. */

import { buildWorkerApplication, installWorkerSignalHandlers } from "./runtime/application.js";
import { loadWorkerRuntimeConfig } from "./runtime/config.js";

const config = loadWorkerRuntimeConfig();
const application = buildWorkerApplication(config);
installWorkerSignalHandlers(application);
await application.start();

// eslint-disable-next-line no-console
console.log(`agent-worker ready on http://localhost:${config.port}`);
