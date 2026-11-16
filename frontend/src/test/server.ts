import { setupServer } from "msw/node";

// Handlers are added per test with server.use(...); unhandled requests fail.
export const server = setupServer();
