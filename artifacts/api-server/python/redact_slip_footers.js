// MuPDF is already a system dependency. Redaction removes the old numbering
// from searchable text as well as from the visible page.
var doc = new PDFDocument(scriptArgs[0]);
var plan = JSON.parse(readFile(scriptArgs[1]).asString());
for (var i = 0; i < plan.length; i++) {
    var page = doc.loadPage(plan[i].page);
    var annotation = page.createAnnotation("Redact");
    annotation.setRect(plan[i].rect);
    // Do not paint a black redaction box; the replacement footer is black text.
    page.applyRedactions(false);
}
doc.save(scriptArgs[2], "garbage=4,compress");
