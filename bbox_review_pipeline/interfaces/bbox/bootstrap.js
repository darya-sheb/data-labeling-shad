// The classic workspace calls assets() and then init() when an SDK asset is late.
function buildAnnotationView(exports) {
__TASK_SCRIPT__
  return exports;
}

if (typeof TolokaHandlebarsTask === 'function') {
  buildAnnotationView(exports);
} else {
  exports.assets = function () {
    var js = ['$TOLOKA_ASSETS/js/toloka-handlebars-templates.js'];
    if (typeof ImageAnnotationEditor !== 'function') js.push('$TOLOKA_ASSETS/js/image-annotation.js');
    return {js: js};
  };
  exports.init = function () { return buildAnnotationView({}); };
}
