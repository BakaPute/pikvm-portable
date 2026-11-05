// Drain real in-flight route handlers; do not swallow test assertions/errors.
async function closeBrowser(browser){
    for(const context of browser.contexts())
        for(const page of context.pages())await page.unrouteAll({behavior:'wait'});
    await browser.close();
}
module.exports={closeBrowser};
