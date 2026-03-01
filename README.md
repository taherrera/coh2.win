This is a copy of the website coh2.win, now hosted in coh2.win.sltech.cl



The idea of adding the website to github is so that everyone who enjoys the game can collaborate, make or propose changes, clean up the website, etc.



As you can notice there are some issues right now with the website, mainly, some images do not show up, so if you can help correcting this, you are welcome.



To change image url:



find . -type f -name "\*.html" -exec perl -pi -e 's|sites/default/files/styles/doctrine/public/2020-05/big-icon8195\\.html\\?itok=1oZlA\_rc|sites/default/files/game\_icons/Icons\_portraits\_unit\_german\_pioneer\_s\_portrait.png|g' {} +



find . -type f -name "\*.html" -exec perl -pi -e 's|sites/default/files/styles/doctrine/public/2020-05/big-icon\\.html|sites/default/files/game\_icons/Icons\_portraits\_unit\_german\_pioneer\_s\_portrait.png|g' {} +





find . -type f -name "\*.html" -exec perl -pi -e 's|sites/default/files/styles/doctrine/public/2020-05/Icons\_portraits\_unit\_german\_mg42\_crew\_s\_portrait557f\\.html|sites/default/files/game\_icons/Icons\_portraits\_unit\_german\_mg42\_crew\_s\_portrait.png|g' {} +





find . -type f -name "\*.html" -exec perl -pi -e 's|sites/default/files/styles/doctrine/public/2020-05/Icons\_portraits\_unit\_german\_mortar\_crew\_s\_portrait6adb\\.html|sites/default/files/game\_icons/Icons\_portraits\_unit\_german\_mortar\_crew\_s\_portrait.png|g' {} +







find . -type f -name "\*.html" -exec perl -pi -e 's|sites/default/files/styles/doctrine/public/2020-05/Icons\_portraits\_unit\_german\_sniper\_s\_portraitcca9\\.html|sites/default/files/game\_icons/Icons\_portraits\_unit\_german\_sniper\_s\_portrait.png|g' {} +





find . -type f -name "\*.html" -exec perl -pi -e 's|sites/default/files/styles/doctrine/public/2020-05/Icons\_portraits\_unit\_german\_ostruppen\_s\_portraita765\\.html|sites/default/files/game\_icons/Icons\_portraits\_unit\_german\_ostruppen\_s\_portrait.png|g' {} +

