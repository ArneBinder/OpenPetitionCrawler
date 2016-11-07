# !/usr/bin/python
# coding: utf-8

import urllib2  # get pages
import time  # to respect page rules

from bs4 import BeautifulSoup as BS
import pprint
import json
import io
from os import listdir, makedirs
from os.path import isfile, join, exists
import Statistics

__author__ = 'Arne Binder'


class OpenPetitionScraper(object):
    def __init__(self, rootUrl, outFolder):
        self.rootUrl = rootUrl  # like "https://www.openpetition.de"
        self.outFolder = outFolder
        # create output folder if necessary
        if not exists(outFolder):
            makedirs(outFolder)

    def requestPage(self, url):
        request = urllib2.Request(self.rootUrl + url, None, {
            'User-Agent': 'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.9.0.7) Gecko/2009021910 Firefox/3.0.7'})
        try:
            print 'request ' + self.rootUrl + url
            document = urllib2.urlopen(request).read()
        except urllib2.HTTPError, err:
            if err.code == 503:
                print "################################################# 503 #################################################"
                time.sleep(30)
                document = request(url)
            else:
                raise
        return document

    def extractPetitionIDs(self, url):
        """
        Extract all petition IDs from an overview page
        :param url: the url suffix of the overview page
        :return: all IDs of petitions found at the overview page
        """
        overviewPage = self.requestPage(url)
        soup = BS(overviewPage.decode('utf-8', 'ignore'), "html.parser")
        aList = soup.select('ul.petitionen-liste li div.text h2 a')

        return [a['href'].split("/")[-1] for a in aList]

    def getPageCountForSection(self, section):
        """
        Extract the count of overview pages from the bottom of the page
        :param section: Select the group of petitions e.g. "in_zeichnung" or "beendet"
        :return: the count of pages with petitions in the selected group
        """
        root_page = self.requestPage("/?status=" + section)
        soup = BS(root_page.decode('utf-8', 'ignore'), "html.parser")
        pager = soup("p", "pager")
        a = pager[0]("a")[-1]
        maxCount = a.text
        return int(maxCount)

    def extractAllPetitionIDs(self, section):
        """
        Exctract all petition IDs for a certain state.
        Search at every overview page for the state.
        :param states: Select the group of petitions e.g. "in_zeichnung" or "beendet"
        :return: A set of all petition IDs in the petition group
        """
        result = []
        # for state in states:
        count = self.getPageCountForSection(section)
        for i in range(1, count):
            result.extend(self.extractPetitionIDs("?status=" + section + "&seite=" + str(i)))
        return set(result)

    def parsePetition(self, id):
        """
        Parse the basic data if the petition
        :param id: the ID of the petition
        :return: basic petition data
        """
        page = self.requestPage("/petition/online/" + id)
        result = {}
        soup = BS(page.decode('utf-8', 'ignore'), "html.parser")
        petition = soup.select('div#main div.content > div > div > div.col2')[0]
        result['claimShort'] = petition.find("h2").text
        content = petition.find("div", "text")

        result['claim'] = content("p")[0].text
        result['ground'] = content("p")[1].text
        return result

    def parseDebate(self, id):
        """
        Parse the debate related to a petition
        :param id: the ID of the petition the debate belongs to
        :return: The pro and con arguments of the debate including its counter arguments
        """
        page = self.requestPage("/petition/argumente/" + id)
        soup = BS(page.decode('utf-8', 'ignore'), "html.parser")
        argGroups = soup.select('div.petition-argumente > div > div > div.col2 > div > div.twocol')

        result = {}
        for argGroup in argGroups:
            articles = argGroup("article")
            args = []

            for article in articles:
                newArgument = {'id': article['data-id']}
                tags = article.find("ul", "tags")
                if tags is not None:
                    newArgument['tags'] = tags.text
                text = article.find("div", "text")
                newArgument['content'] = next(text.strings, "")
                source = text.find('span', 'source')
                if source:
                    newArgument['source'] = source.text
                newArgument['weight'] = article.select('div.tools span.gewicht')[0].text
                newArgument['counterArguments'] = json.loads(
                    self.requestPage("/ajax/argument_replies?id=" + newArgument['id']))
                args.append(newArgument)

            polarity = argGroup.find("h2", "h1").text
            if polarity == "Pro":
                result['pro'] = args
            elif polarity == "Contra":
                result['con'] = args
                # else:
                # print "no"

        return result

    def parseComments(self, petitionID):
        """
        Parse comment data of a petition
        :param petitionID: the ID of the petition the comments belong to
        :return: the comment data
        """
        page = self.requestPage("/petition/kommentare/" + petitionID)
        soup = BS(page.decode('utf-8', 'ignore'), "html.parser")
        comments = soup.select('article.kommentar > div.text')
        return [comment.select(' > p')[1].text for comment in comments]

    def extractPartitionData(self, petitionID):
        """
        Collect all data related to a petition
        :param petitionID: the id of the petition
        :return: the data
        """
        result = self.parsePetition(petitionID)
        result['arguments'] = self.parseDebate(petitionID)
        result['comments'] = self.parseComments(petitionID)
        return result

    def processIDs(self, ids, path):
        idsFailed = []
        for currentID in ids:
            try:
                data = self.extractPartitionData(currentID)
                writeJsonData(data, join(path, currentID))
            except:
                idsFailed.append(currentID)
        writeJsonData(idsFailed, path + "_MISSING")

    def processSections(self, sections):
        for section in sections:
            path = join(self.outFolder, section)
            if exists(path + "_ALL.json"):
                # read id list from file
                with open(path + '_ALL.json') as fileAllIDs:
                    ids = json.load(fileAllIDs)
            else:
                ids = list(self.extractAllPetitionIDs(section))
                writeJsonData(ids, path + "_ALL")

            if not exists(path):
                makedirs(path)
            # get processedIDs from json file
            processedIDs = [f[:-len('.json')] for f in listdir(path) if isfile(join(path, f))]
            ids = [id for id in ids if id not in processedIDs]
            if exists(path + "_MISSING.json"):
                # read id list from file
                with open(path + '_MISSING.json') as fileMissingIDs:
                    missingIDs = json.load(fileMissingIDs)
                ids.extend(missingIDs)
            self.processIDs(ids, path)


def writeJsonData(data, path):
    with io.open(path + '.json', 'w', encoding='utf8') as json_file:
        out = json.dumps(data, ensure_ascii=False)
        # unicode(data) auto-decodes data to unicode if str
        json_file.write(unicode(out))


def argument_row(debate):
    arg_id = 0
    for type in ['con', 'pro']:
        for argument in debate['arguments'][type]:
            arg_id += 1
            reply_id = 0
            yield {'question': debate['claimShort'], 'argument_id':arg_id, 'content':argument['content'].strip(), 'type': type, 'reply_id': reply_id, 'source': argument['source']}
            for reply in argument['counterArguments']:
                reply_id += 1
                yield {'question': debate['claimShort'], 'argument_id':arg_id, 'content': reply['argument_text'].strip(), 'type': 'reply', 'reply_id': reply_id}


def writeTSV(inPath, outPath):
    captions = ['link', 'argument_id', 'reply_id', 'type', 'question', 'content']

    for data, debate_id, section in Statistics.dataFiles(inPath):
        if len(data['arguments']['pro']) + len(data['arguments']['pro']) >= 100:
            records = []
            for arg in argument_row(data):
                # arg['debate_id'] = debate_id
                arg['link'] = "https://www.openpetition.de/petition/argumente/" + debate_id
                records.append(arg)

            with open(join(outPath, section + '_' + debate_id + '.tsv'), 'w') as tsvFile:
                writer = Statistics.UnicodeDictWriter(tsvFile, fieldnames=captions, delimiter='\t', lineterminator='\n')
                writer.writeheader()
                writer.writerows(records)


def main():
    f = OpenPetitionScraper("https://www.openpetition.de", "out")
    f.processSections(["in_zeichnung", "in_bearbeitung", "erfolg", "beendet", "misserfolg"])#, "gesperrt"])
    # Statistics.createCSVStats("out", "stats.tsv")
    # writeTSV("out", "out_tsv")


if __name__ == "__main__":
    main()
