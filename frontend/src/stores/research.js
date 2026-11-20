import {studies,runs,calibrations} from '../api/research.js';
export const store={studies:[],runs:[],calibrations:[],studyId:0,runId:0,rows:[]};
export async function load(){[store.studies,store.runs,store.calibrations]=await Promise.all([studies.list(),runs.list(),calibrations.list()]);if(!store.studyId)store.studyId=store.studies[0]?.id||0;}
export async function loadRows(){store.rows=store.studyId?await studies.rows(store.studyId):[];}
