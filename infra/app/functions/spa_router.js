// CloudFront Function (cloudfront-js-2.0), viewer-request, default (S3) behaviour only.
// /api/* never reaches this function: that behaviour has no function association.
//
//   /                      -> /index.html          SPA fallback
//   /employee, /admin/x    -> /index.html          (last segment has no extension)
//   /assets/app.js         -> unchanged            (has an extension)
//   /seed-sources/...      -> unchanged            hosted seed sources
//   /pr-<n>/               -> /previews/pr-<n>/index.html
//   /pr-<n>/admin/tasks    -> /previews/pr-<n>/index.html
//   /pr-<n>/assets/x.js    -> /previews/pr-<n>/assets/x.js
//
// No dependencies and no module system, so node --test can load it via vm.
function handler(event) {
  var request = event.request;
  var uri = request.uri;

  if (uri.indexOf("/seed-sources/") === 0) {
    return request;
  }

  var prefix = "";
  var rest = uri;
  var preview = /^\/pr-(\d+)(\/.*)?$/.exec(uri);
  if (preview) {
    prefix = "/previews/pr-" + preview[1];
    rest = preview[2] || "/";
  }

  var last = rest.substring(rest.lastIndexOf("/") + 1);
  if (last.indexOf(".") === -1) {
    request.uri = prefix + "/index.html";
  } else {
    request.uri = prefix + rest;
  }
  return request;
}
