// Local artifact smoke check; launches an isolated headless browser, no user profile.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),{pathToFileURL}=require('url');
(async()=>{
 const root=process.env.OFFERLOOP_HOME||path.resolve(__dirname,'..');
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
  page.on('pageerror', e=>errors.push(String(e)));
  await page.goto(pathToFileURL(path.join(root,'求职台账.html')).href);
  const result=await page.evaluate(()=>({rows:document.querySelectorAll('#opportunities tbody tr').length,links:document.querySelectorAll('a').length,width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));
  const firstPlatform=await page.locator('#platform option').nth(1).getAttribute('value');
  await page.locator('#platform').selectOption(firstPlatform);
  const filtered=await page.locator('#opportunities tbody tr:visible').count();
  result.platformFilter=filtered>0&&filtered<result.rows;
  await page.locator('#platform').selectOption('');
  await page.locator('#search').fill('APP-001');
  result.search=await page.locator('#opportunities tbody tr:visible').count()===1;
  await page.locator('#search').fill('');
  await page.screenshot({path:path.join(root,'.local/offerloop/台账预览.png'),fullPage:true});
  await page.setViewportSize({width:760,height:900});
  result.mobile=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));
  result.errors=errors;delete result.text;
  fs.writeFileSync(path.join(root,'.local/offerloop/页面核验.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
  if(result.rows<6||result.links<result.rows||!result.platformFilter||!result.search||errors.length||result.scrollWidth>result.width||result.mobile.scrollWidth>result.mobile.width)process.exitCode=1;
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
