<?php
// Empfängeradresse des Kontaktformulars.
//
// Dieser Platzhalter steht bewusst im Repository. Der Deploy-Workflow
// (.github/workflows/ftp-upload.yml) überschreibt die Datei vor dem Upload
// mit dem Wert aus dem GitHub-Secret CONTACT_MAIL_TO, die echte Adresse
// liegt also weder im öffentlichen Repo noch im ausgelieferten HTML.
//
// .htaccess sperrt den direkten Abruf dieser Datei. Damit bleibt die
// Adresse selbst dann verborgen, wenn der Server einmal kein PHP ausführt.
return '';
